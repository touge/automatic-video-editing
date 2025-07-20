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
from src.color_utils import (
    print_colored,
    print_error,
    print_success,
    print_info,
)
# --- 新增导入 ---
from src.providers.search.pexels import PexelsProvider
from src.providers.search.pixabay import PixabayProvider
from src.providers.search.ai_search import AiSearchProvider
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

        # 新增：从配置中读取API请求延迟，默认为3秒
        self.request_delay = self.asset_search_config.get('request_delay_seconds', 3)
        self.last_online_search_time = None # 新增：用于跟踪上次API调用的时间

        # 初始化数据库管理器
        # self.db_manager = DatabaseManager()
        # os.makedirs(self.local_assets_path, exist_ok=True)

        # --- 全局已用素材跟踪 ---
        self.used_source_ids: Set[str] = set()
        self.used_ai_video_names: Set[str] = set() # 新增：只跟踪来自 ai_search 的 video_name
        self.used_local_paths: Set[str] = set()

        # --- 初始化所有可用的视频提供者 ---
        self.video_providers: List[BaseVideoProvider] = []
        
        # 1. 优先添加AI智能搜索提供者 (最高优先级)
        if config.get('ai_search', {}).get('api_key') and config.get('ai_search', {}).get('api_url'):
            log.success("AI 智能搜索提供者已启用。")
            self.video_providers.append(AiSearchProvider(self.config))

        # 3. 添加其他在线提供者
        if config.get('pexels', {}).get('api_key') and "YOUR_PEXELS_API_KEY_HERE" not in config.get('pexels', {}).get('api_key'):
            log.success("Pexels 提供者已启用。")
            self.video_providers.append(PexelsProvider(self.config))
        if config.get('pixabay', {}).get('api_key') and "YOUR_PIXABAY_API_KEY_HERE" not in config.get('pixabay', {}).get('api_key'):
            log.success("Pixabay 提供者已启用。")
            self.video_providers.append(PixabayProvider(self.config))

        # 移除LLM关键词生成相关代码
        self.llm_manager = None
        self.asset_system_prompt = None
        self.asset_user_prompt_template = None
        log.info("AssetManager 已初始化，LLM关键词生成功能已禁用。")

    def _generate_new_keywords(
        self,
        scene_text: str,
        existing_keywords: Set[str]
    ) -> List[str]:
        # LLM关键词生成已禁用，直接返回空列表
        log.debug("LLM关键词生成已禁用，跳过生成新关键词。")
        return []
    
    def find_assets_for_scene(self, scene: dict, num_assets: int) -> List[Dict[str, Any]]:
        """
        Simplied logic:
        1. Get keywords from the scene.
        2. Use these keywords to find ONE asset.
        3. If found, return it. If not, return empty.
        No more secondary keyword generation or complex logic.
        """
        scene_duration = scene.get("time", 0)
        keywords = scene.get("keys", [])

        if not keywords:
            log.warning("Scene has no keywords. Cannot find assets.")
            return []
            
        log.info(f"Attempting to find asset with keywords: {keywords}")
        
        # This method now finds one asset and returns it in a list, or an empty list.
        found_video_infos = self._find_assets_with_keywords(keywords, num_assets, scene_duration)
    
        if found_video_infos:
            log.success(f"Successfully found an asset for the scene.")
        else:
            log.error(f"Failed to find any usable asset for the scene with keywords: {keywords}")
            
        return found_video_infos
    
    def _find_assets_with_keywords(self, keywords: List[str], num_to_find: int, min_duration: float = 0) -> List[Dict[str, Any]]:
        """
        为一批关键词查找一个可用的素材。
        此方法现在实现了完整的查找、验证、下载逻辑，只返回一个结果。
        """
        if not keywords or not self.video_providers:
            return []

        # The outer logic expects a list, even though we only find one.
        # We will find one valid asset and return it inside a list.
        
        for provider in self.video_providers:
            if not provider.enabled:
                continue
            
            provider_name = provider.__class__.__name__.replace("Provider", "")
            log.info(f"  -> 尝试 Provider: {provider_name}")

            # In this provider, try all keywords until one yields a usable video.
            for keyword in keywords:
                # --- API Request Delay ---
                if self.last_online_search_time:
                    elapsed = time.time() - self.last_online_search_time
                    if elapsed < self.request_delay:
                        sleep_duration = self.request_delay - elapsed
                        log.info(f"    -> API请求间隔为 {self.request_delay}s，等待 {sleep_duration:.2f}s...")
                        time.sleep(sleep_duration)
                self.last_online_search_time = time.time()

                log.info(f"    -> 尝试关键词: '{keyword}'")
                # Get a list of candidate videos from the provider.
                # The `num_to_find` here is passed to the provider's search method as `count`.
                candidate_videos = provider.search([keyword], count=num_to_find, min_duration=min_duration)

                if not candidate_videos:
                    log.warning(f"    -> 在 {provider_name} 中未找到关于 '{keyword}' 的视频。")
                    continue # Try next keyword

                # Iterate through the candidates to find the first usable one.
                for video_info in candidate_videos:
                    unique_id = video_info.get('id')
                    video_name = video_info.get('video_name')
                    source = video_info.get('source')

                    # --- Deduplication Logic ---
                    if unique_id and unique_id in self.used_source_ids:
                        log.warning(f"    -> 跳过已使用的素材 (按 unique_id): {unique_id}")
                        continue
                    if source != 'ai_search' and video_name and video_name in self.used_ai_video_names:
                        log.warning(f"    -> 跳过已被 AI Search 使用的同名素材 (按 video_name): {video_name}")
                        continue
                    if not unique_id:
                        log.warning(f"    -> 跳过一个没有唯一ID的素材: {video_info}")
                        continue

                    # --- Found a new, usable asset ---
                    log.success(f"    -> 在 {provider_name} 中找到新素材: {unique_id} (关键词: '{keyword}')")
                    
                    # Download it.
                    path = self._download_and_register(video_info, keywords)
                    if path:
                        # Mark as used.
                        self.used_source_ids.add(unique_id)
                        if source == 'ai_search':
                            if video_name: self.used_ai_video_names.add(video_name)
                            self.used_local_paths.add(path)
                        
                        # Add local_path to the info and return.
                        video_info['local_path'] = path
                        return [video_info] # Return as a list with one item.
            
            log.warning(f"    -> 在 {provider_name} 中，所有关键词均未找到可用素材。")

        # If we get here, no asset was found in any provider for any keyword.
        log.error(f"  -> 遍历了所有 Provider 和关键词，但未能为该镜头找到任何可用素材。")
        return []

    
    def _download_and_register(self, video_info: Dict[str, Any], keywords: List[str]) -> str | None:
        """
        下载单个视频并返回其本地路径。
        - 对于 'ai_search'，素材被视为临时片段，下载到任务特定的 .videos 目录中。
        - 对于其他提供者，素材被下载到全局的本地资产缓存中。
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
