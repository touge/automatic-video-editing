import os
import requests
import random
import datetime
import time
import re
import uuid
import sys
from src.providers.llm import LlmManager
from typing import List, Set, Dict, Any
from .database_manager import DatabaseManager
from src.logger import log
from src.utils import get_video_duration
# --- 新增导入 ---
from src.providers.search.pexels import PexelsProvider
from src.providers.search.pixabay import PixabayProvider
from src.providers.search.ai_search import AiSearchProvider
from src.providers.search.envato import EnvatoProvider
from src.providers.search.base import BaseVideoProvider

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import AgglomerativeClustering

def dedupe_and_fill(keywords, target=3, threshold=0.6, fallback=None):
    if not keywords:
        return (fallback or [])[:target]

    # If there's only one keyword, no need to dedupe.
    if len(keywords) < 2:
        unique = list(keywords)
    else:
        vec = TfidfVectorizer().fit_transform(keywords)
        clustering = AgglomerativeClustering(
            n_clusters=None,
        metric='cosine',
        linkage='average',
            distance_threshold=1 - threshold,
            compute_full_tree=True
        ).fit(vec.toarray())
        labels = clustering.labels_

        unique, seen = [], set()
        for idx, lab in enumerate(labels):
            if lab not in seen:
                unique.append(keywords[idx])
                seen.add(lab)

    # 补齐
    extra = fallback or []
    for w in extra:
        if len(unique) >= target:
            break
        if w not in unique:
            unique.append(w)

    return unique[:target]

class AssetManager:
    def __init__(self, config: dict, task_id: str):
        self.config = config
        self.task_id = task_id
        self.local_assets_path = config.get('paths', {}).get('local_assets_dir', 'assets/local')
        self.asset_search_config = config.get('asset_search', {})
        self.search_providers_config = config.get('search_providers', {})

        # 新增：从配置中读取API请求延迟，默认为3秒
        self.request_delay = self.asset_search_config.get('request_delay_seconds', 3)
        self.last_online_search_time = None # 新增：用于跟踪上次API调用的时间

        # --- 全局已用素材跟踪 ---
        self.used_source_ids: Set[str] = set()
        self.used_ai_video_names: Set[str] = set()
        self.used_local_paths: Set[str] = set()

        # --- 初始化所有可用的视频提供者 ---
        self.video_providers: List[BaseVideoProvider] = self._load_providers()

        # 移除LLM关键词生成相关代码
        self.llm_manager = None
        self.asset_system_prompt = None
        self.asset_user_prompt_template = None
        log.info("AssetManager 已初始化，LLM关键词生成功能已禁用。")

    def _load_providers(self) -> List[BaseVideoProvider]:
        """根据配置文件加载并排序视频提供者。"""
        providers = []
        provider_order = self.search_providers_config.get('provider_order', [])
        
        provider_map = {
            "ai_search": AiSearchProvider,
            "pexels": PexelsProvider,
            "pixabay": PixabayProvider,
            "envato": EnvatoProvider,
        }

        log.info("正在初始化视频搜索提供者...")
        for provider_name in provider_order:
            provider_config = self.search_providers_config.get(provider_name, {})
            if provider_config.get('enabled'):
                if provider_name in provider_map:
                    try:
                        # 将整个 config 传给 provider，让其自行解析
                        provider_instance = provider_map[provider_name](self.config)
                        # 检查 provider 在初始化后是否仍然启用
                        if provider_instance.enabled:
                            providers.append(provider_instance)
                            log.success(f"提供者 '{provider_name}' 已成功加载并启用。")
                        else:
                            # 初始化过程中提供者自行禁用了（例如，登录失败）
                            log.warning(f"提供者 '{provider_name}' 在初始化后被禁用。")
                    except Exception as e:
                        log.error(f"初始化提供者 '{provider_name}' 失败: {e}")
                else:
                    log.warning(f"在 provider_map 中未找到名为 '{provider_name}' 的提供者。")
            else:
                log.info(f"提供者 '{provider_name}' 在配置中被禁用，跳过加载。")
        
        return providers

    def _generate_new_keywords(
        self,
        scene_text: str,
        existing_keywords: Set[str]
    ) -> List[str]:
        # LLM关键词生成已禁用，直接返回空列表
        log.debug("LLM关键词生成已禁用，跳过生成新关键词。")
        return []
    
    def find_assets_for_scene(self, scene: dict, online_search_count: int) -> List[Dict[str, Any]]:
        """
        为单个场景查找一个最终可用的素材。
        它会遍历所有提供者和关键词，对返回的每个候选素材进行下载和验证，
        一旦找到第一个完全可用的素材，就立即返回。
        """
        scene_duration = scene.get("time", 0)
        keywords = scene.get("keys", [])

        if not keywords:
            log.warning("场景中没有关键词，无法查找素材。")
            return []
            
        log.info(f"\n正在为场景查找素材，关键词: {keywords}")
        
        # 此方法现在查找、下载、验证并返回一个可用的素材，或返回空列表
        found_video_info = self._find_and_validate_asset(keywords, online_search_count, scene_duration)
    
        if found_video_info:
            log.success(f"成功为场景找到并验证了素材。")
            return [found_video_info] # 以列表形式返回单个结果
        else:
            log.error(f"未能为场景找到任何可用的素材，关键词: {keywords}")
            return []

    def _find_and_validate_asset(self, keywords: List[str], search_count_per_call: int, min_duration: float = 0) -> Dict[str, Any] | None:
        """
        遍历所有Provider和关键词，查找、下载并验证第一个可用的素材。
        """
        if not keywords or not self.video_providers:
            return None

        for provider in self.video_providers:
            if not provider.enabled:
                continue
            
            provider_name = provider.__class__.__name__.replace("Provider", "")
            log.info(f"  -> 尝试 Provider: {provider_name}")

            for keyword in keywords:
                # --- API 请求延迟 ---
                if self.last_online_search_time:
                    elapsed = time.time() - self.last_online_search_time
                    if elapsed < self.request_delay:
                        sleep_duration = self.request_delay - elapsed
                        log.info(f"    -> API请求间隔为 {self.request_delay}s，等待 {sleep_duration:.2f}s...")
                        time.sleep(sleep_duration)
                self.last_online_search_time = time.time()

                log.info(f"    -> 尝试关键词: '{keyword}'")
                
                # 从Provider获取一批候选视频
                candidate_videos = provider.search([keyword], count=search_count_per_call, min_duration=min_duration)

                if not candidate_videos:
                    log.warning(f"    -> 在 {provider_name} 中未找到关于 '{keyword}' 的视频。")
                    continue # 尝试下一个关键词

                # 遍历这批候选视频，找到第一个完全可用的
                for video_info in candidate_videos:
                    unique_id = video_info.get('id')
                    video_name = video_info.get('video_name')
                    source = video_info.get('source')

                    # --- 去重逻辑 ---
                    if unique_id and unique_id in self.used_source_ids:
                        log.warning(f"    -> 跳过已使用的素材 (按 unique_id): {unique_id}")
                        continue
                    if source != 'ai_search' and video_name and video_name in self.used_ai_video_names:
                        log.warning(f"    -> 跳过已被 AI Search 使用的同名素材 (按 video_name): {video_name}")
                        continue
                    if not unique_id:
                        log.warning(f"    -> 跳过一个没有唯一ID的素材: {video_info}")
                        continue

                    # --- 特殊处理 Envato Provider (它已经自行下载) ---
                    if source == 'envato':
                        local_path = video_info.get('local_path')
                        if local_path and os.path.exists(local_path) and get_video_duration(local_path) is not None:
                            log.success(
                                f"    -> Envato 已成功下载并验证素材: {local_path}")
                            path = local_path
                        else:
                            log.warning(
                                f"    -> Envato 返回的素材无效或不存在: {local_path}。尝试下一个候选素材。")
                            continue
                    else:
                        # --- 其他 Provider 的标准下载流程 ---
                        log.success(
                            f"    -> 在 {provider_name} 中找到新候选素材: {unique_id} (关键词: '{keyword}')。正在尝试下载和验证...")
                        path = self._download_asset(video_info)
                        if not path:
                            log.warning(f"    -> 下载失败，尝试下一个候选素材。")
                            continue

                    # --- 标记为已使用并返回 ---
                    self.used_source_ids.add(unique_id)
                    if source == 'ai_search':
                        if video_name: self.used_ai_video_names.add(video_name)
                        self.used_local_paths.add(path)
                    
                    video_info['local_path'] = path
                    return video_info # 成功，立即返回
            
            log.warning(f"    -> 在 {provider_name} 中，所有关键词均未找到可用素材。")

        log.error(f"  -> 遍历了所有 Provider 和关键词，但未能为该镜头找到任何可用素材。")
        return None

    
    def _download_asset(self, video_info: Dict[str, Any]) -> str | None:
        """
        下载单个视频，验证其有效性，然后返回其本地路径。
        如果下载或验证失败，则返回 None。
        """
        source = video_info['source']
        source_id = video_info['id']
        download_url = video_info['download_url']

        # --- AI Search 特殊处理：下载到任务临时目录 ---
        if source == 'ai_search':
            task_videos_dir = os.path.join('tasks', self.task_id, '.videos', 'ai_search_temp')
            os.makedirs(task_videos_dir, exist_ok=True)
            
            filename = f"ai-search-{uuid.uuid4()}.mp4"
            local_file_path = os.path.join(task_videos_dir, filename)

            try:
                log.info(f"      -> 正在下载 AI 搜索素材片段: {filename}")
                video_res = requests.get(download_url, timeout=60, stream=True)
                video_res.raise_for_status()
        
                total_size = int(video_res.headers.get('content-length', 0))
                from tqdm import tqdm
                with open(local_file_path, 'wb') as f, tqdm(
                    desc=f"      -> {filename}",
                    total=total_size,
                    unit='iB',
                    unit_scale=True,
                    unit_divisor=1024,
                    leave=False
                ) as bar:
                    for chunk in video_res.iter_content(chunk_size=8192):
                        size = f.write(chunk)
                        bar.update(size)
                
                log.success(f"      -> AI 搜索素材已下载到临时目录: {local_file_path}")
                
                # 下载后立即验证
                if get_video_duration(local_file_path) is None:
                    log.error(f"      -> 下载的文件无效 (无法获取时长): {local_file_path}。正在删除...")
                    os.remove(local_file_path)
                    return None
                
                return local_file_path
            except KeyboardInterrupt:
                log.error("用户中断了下载操作。")
                if os.path.exists(local_file_path):
                    os.remove(local_file_path)
                sys.exit(0)
            except Exception as download_e:
                log.error(f"      -> 下载 AI 搜索素材 {source_id} 失败: {download_e}", exc_info=True)
                if os.path.exists(local_file_path):
                    os.remove(local_file_path)
                return None

        # --- 其他 Provider 的标准处理流程 ---
        # 检查数据库中是否已存在此视频
        # existing_path = self.db_manager.find_asset_by_source_id(source, str(source_id))
        # if existing_path:
        #     log.info(f"      -> 在本地缓存中找到素材 (来自数据库): {os.path.basename(existing_path)}")
        #     return existing_path
    
        # 如果不在缓存中，则创建日期子目录后下载
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        daily_dir = os.path.join(self.local_assets_path, today_str)
        os.makedirs(daily_dir, exist_ok=True)
        
        filename = f"{source_id}.mp4"
        local_file_path = os.path.join(daily_dir, filename)
    
        try:
            log.info(f"      -> 正在下载新素材: {filename} from {source}")
            video_res = requests.get(download_url, timeout=60, stream=True)
            video_res.raise_for_status()
    
            # 为下载添加tqdm进度条
            total_size = int(video_res.headers.get('content-length', 0))
            from tqdm import tqdm
            with open(local_file_path, 'wb') as f, tqdm(
                desc=f"      -> {filename}",
                total=total_size,
                unit='iB',
                unit_scale=True,
                unit_divisor=1024,
                leave=False # 下载完成后进度条消失
            ) as bar:
                for chunk in video_res.iter_content(chunk_size=8192):
                    size = f.write(chunk)
                    bar.update(size)
            
            # 下载成功后，注册到数据库
            # self.db_manager.add_asset(source, str(source_id), keywords, local_file_path)
            # log.success(f"      -> 视频已下载并索引: {local_file_path}")

            # 下载后立即验证
            if get_video_duration(local_file_path) is None:
                log.error(f"      -> 下载的文件无效 (无法获取时长): {local_file_path}。正在删除...")
                os.remove(local_file_path)
                return None

            return local_file_path
        except KeyboardInterrupt:
            log.error("用户中断了下载操作。")
            if os.path.exists(local_file_path):
                os.remove(local_file_path)
            sys.exit(0)
        except Exception as download_e:
            log.error(f"      -> 下载视频 {source_id} 失败: {download_e}", exc_info=True)
            # 如果下载失败，清理可能已创建的不完整文件
            if os.path.exists(local_file_path):
                os.remove(local_file_path)
            return None
