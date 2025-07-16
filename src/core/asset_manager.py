import os
import requests
import random
import datetime
import time
import re
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

        self.llm_manager = LlmManager(config)
        if not self.llm_manager.ordered_providers:
            raise ValueError("No LLM providers are available for AssetManager. Please check your config.yaml.")
        log.info("AssetManager initialized for keyword generation.")

        # 从配置中加载素材关键词生成提示词
        prompts_config = self.config.get('prompts', {})
        asset_prompt_config = prompts_config.get('asset_keyword_generator')
        if not asset_prompt_config or 'system' not in asset_prompt_config or 'user' not in asset_prompt_config:
            raise ValueError("Asset keyword generator prompt 'prompts.asset_keyword_generator' with 'system' and 'user' keys not found in config.yaml")
        self.asset_system_prompt = asset_prompt_config['system']
        self.asset_user_prompt_template = asset_prompt_config['user']

        # as_cfg = config.get("asset_search", {})
        self.fallback_en = self.asset_search_config.get("fallback_en", [])
        self.fallback_cn = self.asset_search_config.get("fallback_cn", [])

    def _generate_new_keywords(
        self,
        scene_text: str,
        existing_keywords: Set[str]
    ) -> List[str]:
        """
        使用 Ollama 生成新的、不重复的英文关键词，并做语义去重+补齐到 3 条。
        existing_keywords: 已尝试过的关键词集合（小写）。
        返回长度恒为 3 的关键词列表（可能包含 fallback）。
        """
        log.info("  -> 调用 Ollama 生成新的关键词…")
        # 1. 构造 Prompt
        user_prompt = self.asset_user_prompt_template.format(
            existing_keywords=', '.join(existing_keywords),
            scene_text=scene_text
        )
        
        try:
            # 2. 调用 Ollama Chat 接口
            content = self.llm_manager.chat_with_failover(
                messages=[
                    {'role': 'system', 'content': self.asset_system_prompt},
                    {'role': 'user',   'content': user_prompt}
                ],
                temperature=0.7
            )
    
            # 3. 去掉模型可能输出的 <think>…</think> 块
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
    
            # 4. 清洗并拆分成候选关键词
            cleaned = content.replace('"', '').replace("'", "").strip()
            potential_keywords = [kw.strip() for kw in cleaned.split(',') if kw.strip()]
    
            # 5. 简单过滤：不超过 5 个单词
            validated = []
            for kw in potential_keywords:
                if len(kw.split()) <= 5:
                    validated.append(kw)
                else:
                    log.warning(f"已过滤掉过长的潜在关键词: '{kw}'")
    
            # 6. 排除已尝试过的重复关键词
            final_new = [kw for kw in validated if kw.lower() not in existing_keywords]
    
            # 7. 语义去重 + 补齐到 3 条
            enriched = dedupe_and_fill(
                final_new,
                target=3,
                threshold=0.6,
                fallback=self.fallback_en
            )
    
            log.info(f"  -> Ollama 生成的新关键词（去重+补齐后）: {enriched}")
            return enriched
    
        except Exception as e:
            log.warning(f"Failed to generate keywords with LLM provider: {e}", exc_info=True)
            # 失败时直接返回 fallback（去重）
            return dedupe_and_fill(
                [],
                target=3,
                fallback=self.fallback_en
            )
    
    
    def find_assets_for_scene(self, scene: dict, num_assets: int) -> list[str]:
        """
        1) 对 scene['keywords_en'] 先去重补齐到 3 条，得到 initial_keywords
        2) 用 initial_keywords 搜素材；若失败，生成新关键词（_generate_new_keywords 已经做过去重补齐）
        3) 最终返回找到的素材路径
        """
    
        # —— 第一步：处理初始关键词 ——
        raw_initial = scene.get("keywords_en", [])
        initial_keywords = dedupe_and_fill(
            raw_initial,
            target=3,
            fallback=self.fallback_en
        )
    
        # 把首轮的关键词放入 tried，用于后面避免重复
        tried = set(kw.lower() for kw in initial_keywords)
    
        current_keywords = initial_keywords
    
        # —— 第二步：尝试多轮搜索 ——
        max_retries = self.asset_search_config.get("max_keyword_retries", 2)
        for round_idx in range(max_retries + 1):
            log.info(f"[轮次 {round_idx+1}] 用关键词 {current_keywords} 搜素材")
            found = self._find_assets_with_keywords(current_keywords, num_assets)
    
            if len(found) >= num_assets:
                log.success(f"找到了 {len(found)} 个素材，返回！")
                return found
    
            # 如果本轮不够，且还没到最大重试次数，就生成新关键词重试
            if round_idx < max_retries:
                new_kw = self._generate_new_keywords(scene['text'], tried)
                # _generate_new_keywords 内部也会调用 dedupe_and_fill，保证 new_kw 长度=3、无重复
                if not new_kw:
                    break
                # 更新 tried，防止下次 _generate_new_keywords 出现重复
                tried.update(kw.lower() for kw in new_kw)
                current_keywords = new_kw
            else:
                log.warning("已到重试上限，退出。")
    
        # 所有轮次都没凑够，返回已有素材（可能为空）
        return found
    
    def _find_assets_with_keywords(self, keywords: List[str], num_to_find: int) -> List[str]:
        """
        为一批关键词查找指定数量的素材。
        此方法现在只负责调用 _find_one_asset 指定次数。
        """
        if not keywords:
            return []
    
        found_paths: List[str] = []
        for i in range(num_to_find):
            log.info(f"--- 正在为第 {i+1}/{num_to_find} 个素材片段查找 ---")
            asset_path = self._find_one_asset(keywords)
            if asset_path:
                found_paths.append(asset_path)
            else:
                log.error(f"未能为第 {i+1} 个片段找到任何素材，停止查找。")
                break
        
        return found_paths

    def _find_one_asset(self, keywords: List[str]) -> str | None:
        """
        为一组关键词查找一个素材。
        外层循环遍历 Providers，内层循环遍历关键词。
        """
        if not self.video_providers:
            return None

        for provider in self.video_providers:
            if not provider.enabled:
                continue
            
            provider_name = provider.__class__.__name__.replace("Provider", "")
            log.info(f"  -> 尝试 Provider: {provider_name}")

            # 在当前 Provider 中尝试所有关键词
            video_info = self._search_with_keywords_in_provider(keywords, provider)
            
            if video_info:
                # 找到了，下载并返回
                path = self._download_and_register(video_info, keywords)
                if path:
                    # 从 video_info 中获取正确的唯一ID并标记为已使用
                    unique_id_to_add = video_info.get('unique_id_for_check')
                    if unique_id_to_add:
                        self.used_source_ids.add(unique_id_to_add)
                    else:
                        # 作为后备，如果 unique_id_for_check 不存在，记录一个警告
                        log.warning(f"未能为视频找到 'unique_id_for_check'，将使用原始ID: {video_info.get('id')}")
                        self.used_source_ids.add(video_info.get('id'))

                    # 如果是本地文件，也添加到 used_local_paths
                    if video_info.get('source') == 'ai_search':
                         self.used_local_paths.add(path)
                    return path
        
        log.warning(f"  -> 遍历了所有 Provider，但未能为关键词 {keywords} 找到任何素材。")
        return None

    def _search_with_keywords_in_provider(self, keywords: List[str], provider: BaseVideoProvider) -> Dict[str, Any] | None:
        """
        在单个 Provider 中，按顺序尝试所有关键词，直到找到一个可用的素材。
        """
        provider_name = provider.__class__.__name__.replace("Provider", "")
        for keyword in keywords:
            # --- API请求延迟逻辑 ---
            if self.last_online_search_time:
                elapsed = time.time() - self.last_online_search_time
                if elapsed < self.request_delay:
                    sleep_duration = self.request_delay - elapsed
                    log.info(f"    -> API请求间隔为 {self.request_delay}s，等待 {sleep_duration:.2f}s...")
                    time.sleep(sleep_duration)
            self.last_online_search_time = time.time()

            log.info(f"    -> 尝试关键词: '{keyword}'")
            search_count = self.asset_search_config.get('online_search_count', 10)
            video_results = provider.search([keyword], count=search_count)
            # log.info(f"    -> {provider_name} 返回了 {len(video_results)} 个结果。")
            # log.info(f"    -> 关键词 '{keyword}' 的搜索结果: {video_results}")
            # log.info(f"    -> 当前已被使用过的视频ids: {self.used_source_ids}")

            if not video_results:
                log.warning(f"    -> 在 {provider_name} 中未找到关于 '{keyword}' 的视频。")
                continue # 尝试下一个关键词

            # 遍历返回的视频结果
            for video_info in video_results:
                source = video_info.get('source')
                
                # 根据来源确定唯一标识符
                if source == 'ai_search':
                    unique_id = video_info.get('download_url')
                else:
                    unique_id = video_info.get('id')

                # 如果没有唯一ID，则跳过此素材
                if not unique_id:
                    log.warning(f"    -> 跳过一个没有唯一ID的素材: {video_info}")
                    continue

                # 检查此唯一ID是否已被使用
                if unique_id not in self.used_source_ids:
                    log.success(f"    -> 在 {provider_name} 中找到新素材: {unique_id} (关键词: '{keyword}')")
                    # 将唯一ID存入字典，以便上层方法使用
                    video_info['unique_id_for_check'] = unique_id
                    return video_info
            
            log.warning(f"    -> {provider_name} 为关键词 '{keyword}' 返回的所有素材均已被使用。")

        # 在这个 provider 中，所有关键词都试过了，没找到
        return None
    
    def _download_and_register(self, video_info: Dict[str, Any], keywords: List[str]) -> str | None:
        """下载单个视频，注册到数据库，并返回本地路径。如果已存在则直接返回路径。"""
        source = video_info['source']
        source_id = video_info['id']
        download_url = video_info['download_url']
    
        # 检查数据库中是否已存在此视频
        # existing_path = self.db_manager.find_asset_by_source_id(source, str(source_id))
        # if existing_path:
        #     log.info(f"      -> 在本地缓存中找到素材 (来自数据库): {os.path.basename(existing_path)}")
        #     return existing_path
    
        # 如果源是 'local' 或 'ai_search'，则文件已在本地，无需下载，只需注册
        if source == 'ai_search':
            local_file_path = download_url # 对于本地提供者，download_url就是文件路径
            if os.path.exists(local_file_path):
                # 将其添加到数据库以供未来快速查找
                # self.db_manager.add_asset(source, str(source_id), keywords, local_file_path)
                # log.success(f"      -> 找到并索引了本地素材: {os.path.basename(local_file_path)}")
                return local_file_path
            else:
                log.warning(f"本地提供者报告了一个不存在的文件: {local_file_path}")
                return None
    
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
        except Exception as download_e:
            log.error(f"      -> 下载视频 {source_id} 失败: {download_e}", exc_info=True)
            # 如果下载失败，清理可能已创建的不完整文件
            if os.path.exists(local_file_path):
                os.remove(local_file_path)
            return None
