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
    print_warning,
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
        self.db_manager = DatabaseManager()
        os.makedirs(self.local_assets_path, exist_ok=True)

        # --- 初始化所有可用的视频提供者 ---
        self.video_providers: List[BaseVideoProvider] = []
        
        # 1. 优先添加AI智能搜索提供者 (最高优先级)
        if config.get('ai_search', {}).get('api_key') and config.get('ai_search', {}).get('api_url'):
            print_success("AI 智能搜索提供者已启用。")
            self.video_providers.append(AiSearchProvider(self.config))


        # 3. 添加其他在线提供者
        if config.get('pexels', {}).get('api_key') and "YOUR_PEXELS_API_KEY_HERE" not in config.get('pexels', {}).get('api_key'):
            print_success("Pexels 提供者已启用。")
            self.video_providers.append(PexelsProvider(self.config))
        if config.get('pixabay', {}).get('api_key') and "YOUR_PIXABAY_API_KEY_HERE" not in config.get('pixabay', {}).get('api_key'):
            print_success("Pixabay 提供者已启用。")
            self.video_providers.append(PixabayProvider(self.config))

        llm_manager = LlmManager(config)
        self.llm_provider = llm_manager.default
        if not self.llm_provider:
            raise ValueError("No default LLM provider is available for AssetManager. Please check your config.yaml.")
        log.info(f"AssetManager is using LLM provider for keyword generation: '{self.llm_provider.name}'")

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

    # def _generate_new_keywords(self, scene_text: str, existing_keywords: Set[str]) -> List[str]:
    #     """使用Ollama根据场景文本生成新的、不重复的关键词。"""
    #     print_info("  -> 调用Ollama生成新的关键词...")
    #     user_prompt = self.asset_user_prompt_template.format(
    #         existing_keywords=', '.join(existing_keywords),
    #         scene_text=scene_text
    #     )
    #     try:
    #         response = self.ollama_client.chat(
    #             model=self.ollama_config.get('model'),
    #             messages=[
    #                 {'role': 'system', 'content': self.asset_system_prompt},
    #                 {'role': 'user', 'content': user_prompt}
    #             ],
    #             options={'temperature': 0.7}
    #         )
    #         content = response['message']['content'].strip()

    #         # 阶段 1: 使用正则表达式移除模型可能包含的 <think>...</think> 思考过程块
    #         # re.DOTALL 标志确保可以处理多行思考过程。
    #         content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)

    #         # 阶段 2: 清理并分割成潜在关键词
    #         cleaned_content = content.strip().replace('"', '').replace("'", "")
    #         potential_keywords = [kw.strip() for kw in cleaned_content.split(',') if kw.strip()]

    #         # 阶段 3: 根据关键词的特征（如长度、词数）进行过滤，排除明显不是关键词的长句。
    #         # 规则：一个有效的关键词短语不应超过5个单词。
    #         validated_keywords = []
    #         for kw in potential_keywords:
    #             if len(kw.split()) <= 5:
    #                 validated_keywords.append(kw)
    #             else:
    #                 # 记录下被过滤掉的内容，便于调试
    #                 log.warning(f"已过滤掉过长的潜在关键词: '{kw}'")

    #         # 阶段 4: 过滤掉已存在的重复关键词
    #         final_new_keywords = [kw for kw in validated_keywords if kw.lower() not in existing_keywords]

    #         # ------ 在这里集成去重+补齐 ------
    #         fallback_en = ["healthy lifestyle", "wellness routine", "exercise motion"]
    #         re_final_new_keywords= dedupe_and_fill(final_new_keywords, target=3, threshold=0.6, fallback=fallback_en)
    
    #         print_info(f"  -> Ollama生成的新关键词: {re_final_new_keywords}")
    #         return re_final_new_keywords
    #     except Exception as e:
    #         log.warning(f"调用Ollama生成关键词时出错: {e}", exc_info=True)
    #         return []
    
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
        print_info("  -> 调用 Ollama 生成新的关键词…")
        # 1. 构造 Prompt
        user_prompt = self.asset_user_prompt_template.format(
            existing_keywords=', '.join(existing_keywords),
            scene_text=scene_text
        )
        
        try:
            # 2. 调用 Ollama Chat 接口
            content = self.llm_provider.chat(
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
    
            print_info(f"  -> Ollama 生成的新关键词（去重+补齐后）: {enriched}")
            return enriched
    
        except Exception as e:
            log.warning(f"调用 LLM provider '{self.llm_provider.name}' 生成关键词时出错: {e}", exc_info=True)
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
        # fallback_en 用来保证即便 raw_initial 少于 3 条，也能补齐
        # fallback_en = ["healthy lifestyle", "wellness routine", "exercise motion"]
        # initial_keywords = dedupe_and_fill(raw_initial, target=3, fallback=fallback_en)
    
        # 把首轮的关键词放入 tried，用于后面避免重复
        tried = set(kw.lower() for kw in initial_keywords)
    
        current_keywords = initial_keywords
    
        # —— 第二步：尝试多轮搜索 ——
        max_retries = self.asset_search_config.get("max_keyword_retries", 2)
        for round_idx in range(max_retries + 1):
            print_info(f"[轮次 {round_idx+1}] 用关键词 {current_keywords} 搜素材")
            found = self._find_assets_with_keywords(current_keywords, num_assets)
    
            if len(found) >= num_assets:
                print_success(f"找到了 {len(found)} 个素材，返回！")
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
                print_warning("已到重试上限，退出。")
    
        # 所有轮次都没凑够，返回已有素材（可能为空）
        return found
    # def find_assets_for_scene(self, scene: dict, num_assets: int) -> List[str]:
    #     """
    #     为单个场景查找指定数量的素材。
    #     如果初始关键词失败，会使用Ollama生成新关键词并重试。
    #     """
    #     initial_keywords = scene.get('keywords_en', [])
    #     if not initial_keywords:
    #         log.warning("场景没有关键词，无法搜索素材。")
    #         return []
    
    #     max_retries = self.asset_search_config.get('max_keyword_retries', 2)
    #     tried_keywords: Set[str] = set(kw.lower() for kw in initial_keywords)
    #     current_keywords = initial_keywords
    
    #     for i in range(max_retries + 1):  # +1 for the initial attempt
    #         print_info(f"[第 {i+1}/{max_retries+1} 轮] 为场景 \"{scene['text'][:20]}...\" 搜索 {num_assets} 个素材")
    #         print_info(f"  -> 使用关键词: {current_keywords}")
    
    #         found_assets = self._find_assets_with_keywords(current_keywords, num_assets)
            
    #         if len(found_assets) >= num_assets:
    #             print_success(f"成功！为该场景找到 {len(found_assets)} 个素材。")
    #             return found_assets
            
    #         log.warning(f"查找失败，只找到 {len(found_assets)}/{num_assets} 个素材。")
    
    #         if i < max_retries:
    #             print_info("准备生成新关键词并重试...")
    #             new_keywords = self._generate_new_keywords(scene['text'], tried_keywords)
    #             if not new_keywords:
    #                 log.warning("Ollama未能生成有效的新关键词。停止此场景的搜索。")
    #                 break  # 如果Ollama失败，则停止重试
                
    #             current_keywords = new_keywords
    #             tried_keywords.update(kw.lower() for kw in new_keywords)
    #         else:
    #             log.warning("已达到最大重试次数，停止搜索。")
    
    #     return []
    
    def _find_assets_with_keywords(self, keywords: List[str], num_to_find: int) -> List[str]:
        """
        按顺序为每个需要的片段查找素材。
        它会循环使用关键词列表，直到找到足够数量的片段或尝试完所有可能。
        """
        if not keywords:
            return []
    
        found_paths: List[str] = []
        used_source_ids: Set[str] = set()  # 跟踪在线素材的ID，避免重复下载
        used_local_paths: Set[str] = set() # 跟踪本地素材的路径，避免重复使用
    
        for i in range(num_to_find):
            # 按顺序循环使用关键词
            keyword_for_this_shot = [keywords[i % len(keywords)]]
            print_info(f"    - 正在为片段 {i+1}/{num_to_find} 搜索，关键词: '{keyword_for_this_shot[0]}'")
            
            asset_path = self._find_one_asset(keyword_for_this_shot, used_source_ids, used_local_paths)
    
            if asset_path:
                found_paths.append(asset_path)
            else:
                log.warning(f"      -> 未能为关键词 '{keyword_for_this_shot[0]}' 找到任何可用素材。")
        
        return found_paths
    
    def _find_one_asset(self, keyword: List[str], used_source_ids: Set[str], used_local_paths: Set[str]) -> str | None:
        """
        为单个关键词查找一个素材，优先本地，其次在线。
        此函数会更新 used_source_ids 和 used_local_paths 以避免重复。
        """
        # 1. 在本地数据库中搜索
        local_candidates = self.db_manager.find_assets_by_keywords(keyword, limit=5)
        for path in local_candidates:
            if path not in used_local_paths:
                print_info(f"      -> 在本地数据库找到: {os.path.basename(path)}")
                used_local_paths.add(path)
                return path
    
        # 2. 如果本地没有，则在线搜索
        print_info(f"      -> 本地未找到，转为在线搜索...")
        video_info = self._search_online_for_one(keyword, used_source_ids)
        if video_info:
            # 下载并注册（此函数内部会再次检查数据库，这是安全的）
            path = self._download_and_register(video_info, keyword)
            if path:
                used_source_ids.add(video_info['id'])
                used_local_paths.add(path) # 确保新下载的素材不会在同一场景中被再次选中
                return path
        
        return None
    
    def _search_online_for_one(self, keywords: List[str], used_source_ids: Set[str]) -> Dict[str, Any] | None:
        """使用所有提供者在线搜索一个未被使用过的素材。"""
        if not self.video_providers:
            return None
    
        # 移除 random.shuffle，以确保按照提供者列表的顺序（即优先级）进行搜索
        # random.shuffle(self.video_providers)
 
        for provider in self.video_providers:
            # 检查 provider 是否已被禁用
            if not provider.enabled:
                provider_name = provider.__class__.__name__.replace("Provider", "")
                # log.info(f"Provider '{provider_name}' is disabled, skipping.")
                continue

            # --- 新增：API请求延迟逻辑 ---
            # 对非本地提供者（即需要API调用的）应用延迟
            # LocalProvider 速度快且不访问外部API，因此跳过它。
            # 对所有提供者应用延迟，因为它们都通过网络API调用
            if self.last_online_search_time:
                elapsed = time.time() - self.last_online_search_time
                if elapsed < self.request_delay:
                    sleep_duration = self.request_delay - elapsed
                    print_info(f"      -> API请求间隔为 {self.request_delay}s，等待 {sleep_duration:.2f}s...")
                    time.sleep(sleep_duration)
            
            # 记录本次API调用的时间，以便计算下一次的间隔
            self.last_online_search_time = time.time()
    
            provider_name = provider.__class__.__name__.replace("Provider", "")
            print_info(f"        -> 尝试通过 {provider_name} 搜索...")
            # 从配置中读取要请求的视频数量，默认为10
            search_count = self.asset_search_config.get('online_search_count', 10)
            video_results = provider.search(keywords, count=search_count)
    
            if not video_results:
                log.warning(f"        -> {provider_name} 未找到关于 '{' '.join(keywords)}' 的视频。")
                continue
    
            # 找到第一个尚未在本场景中使用的视频
            for video_info in video_results:
                if video_info['id'] not in used_source_ids:
                    print_success(f"        -> {provider_name} 找到新素材: {video_info['id']}")
                    return video_info
            
            log.warning(f"        -> {provider_name} 找到的素材都已被使用过。")
    
        return None # 所有提供者都尝试过，未找到新素材
    
    def _download_and_register(self, video_info: Dict[str, Any], keywords: List[str]) -> str | None:
        """下载单个视频，注册到数据库，并返回本地路径。如果已存在则直接返回路径。"""
        source = video_info['source']
        source_id = video_info['id']
        download_url = video_info['download_url']
    
        # 检查数据库中是否已存在此视频
        existing_path = self.db_manager.find_asset_by_source_id(source, str(source_id))
        if existing_path:
            print_info(f"      -> 在本地缓存中找到素材 (来自数据库): {os.path.basename(existing_path)}")
            return existing_path
    
        # 如果源是 'local' 或 'ai_search'，则文件已在本地，无需下载，只需注册
        if source == 'ai_search':
            local_file_path = download_url # 对于本地提供者，download_url就是文件路径
            if os.path.exists(local_file_path):
                # 将其添加到数据库以供未来快速查找
                self.db_manager.add_asset(source, str(source_id), keywords, local_file_path)
                print_success(f"      -> 找到并索引了本地素材: {os.path.basename(local_file_path)}")
                return local_file_path
            else:
                log.warning(f"本地提供者报告了一个不存在的文件: {local_file_path}")
                return None
    
        # 如果不在缓存中，则下载
        # 创建日期子目录
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        daily_dir = os.path.join(self.local_assets_path, today_str)
        os.makedirs(daily_dir, exist_ok=True)
        
        filename = f"{source_id}.mp4"
        local_file_path = os.path.join(daily_dir, filename)
    
        try:
            print_info(f"      -> 正在下载新素材: {filename} from {source}")
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
            self.db_manager.add_asset(source, str(source_id), keywords, local_file_path)
            print_success(f"      -> 视频已下载并索引: {local_file_path}")
            return local_file_path
        except Exception as download_e:
            log.error(f"      -> 下载视频 {source_id} 失败: {download_e}", exc_info=True)
            # 如果下载失败，清理可能已创建的不完整文件
            if os.path.exists(local_file_path):
                os.remove(local_file_path)
            return None