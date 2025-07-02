import os
import requests
import random
import datetime
import ollama
from typing import List, Set
from .database_manager import DatabaseManager
from src.logger import log
from src.color_utils import (
    print_colored,
    print_error,
    print_warning,
    print_success,
    print_info,
)
class AssetManager:
    def __init__(self, config: dict, task_id: str):
        self.config = config
        self.task_id = task_id
        self.local_assets_path = config.get('paths', {}).get('local_assets_dir', 'assets/local')
        self.pexels_api_key = config.get('pexels', {}).get('api_key', '')
        self.ollama_config = config.get('ollama', {})
        self.asset_search_config = config.get('asset_search', {})
        # 初始化数据库管理器
        self.db_manager = DatabaseManager()
        os.makedirs(self.local_assets_path, exist_ok=True)

        if not self.ollama_config.get('model'):
            raise ValueError("Ollama model not configured in config.yaml, which is required for generating new keywords.")
        self.ollama_client = ollama.Client(host=self.ollama_config.get('host'))

        # 从配置中加载素材关键词生成提示词
        prompts_config = self.config.get('prompts', {})
        asset_prompt_config = prompts_config.get('asset_keyword_generator')
        if not asset_prompt_config or 'system' not in asset_prompt_config or 'user' not in asset_prompt_config:
            raise ValueError("Asset keyword generator prompt 'prompts.asset_keyword_generator' with 'system' and 'user' keys not found in config.yaml")
        self.asset_system_prompt = asset_prompt_config['system']
        self.asset_user_prompt_template = asset_prompt_config['user']

    def _generate_new_keywords(self, scene_text: str, existing_keywords: Set[str]) -> List[str]:
        """使用Ollama根据场景文本生成新的、不重复的关键词。"""
        print_info("  -> 调用Ollama生成新的关键词...")
        user_prompt = self.asset_user_prompt_template.format(
            existing_keywords=', '.join(existing_keywords),
            scene_text=scene_text
        )
        try:
            response = self.ollama_client.chat(
                model=self.ollama_config.get('model'),
                messages=[
                    {'role': 'system', 'content': self.asset_system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                options={'temperature': 0.7}
            )
            content = response['message']['content'].strip().replace('"', '')
            new_keywords = [kw.strip() for kw in content.split(',') if kw.strip()]
            # 过滤掉Ollama可能仍然返回的重复关键词
            final_new_keywords = [kw for kw in new_keywords if kw.lower() not in existing_keywords]
            print_info(f"  -> Ollama生成的新关键词: {final_new_keywords}")
            return final_new_keywords
        except Exception as e:
            log.warning(f"调用Ollama生成关键词时出错: {e}", exc_info=True)
            return []

    def _find_assets_with_keywords(self, keywords: List[str], num_to_find: int) -> List[str]:
        """使用给定的关键词列表查找指定数量的素材。"""
        if not keywords:
            return []
        
        # 1. 在本地数据库中搜索
        local_found = self.db_manager.find_assets_by_keywords(keywords, num_to_find)
        
        # 2. 如果本地素材不足，在线搜索补充
        remaining_needed = num_to_find - len(local_found)
        if remaining_needed > 0:
            print_info(f"  -> 本地找到 {len(local_found)} 个，仍需在线搜索 {remaining_needed} 个。")
            online_found = self._search_online(keywords, remaining_needed)
            return local_found + online_found
        else:
            print_info(f"  -> 在本地数据库中找到足够数量 ({len(local_found)}) 的素材。")
            return local_found

    def find_assets_for_scene(self, scene: dict, num_assets: int) -> List[str]:
        """
        为单个场景查找指定数量的素材。
        如果初始关键词失败，会使用Ollama生成新关键词并重试。
        """
        initial_keywords = scene.get('keywords_en', [])
        if not initial_keywords:
            log.warning("场景没有关键词，无法搜索素材。")
            return []

        max_retries = self.asset_search_config.get('max_keyword_retries', 2)
        tried_keywords: Set[str] = set(kw.lower() for kw in initial_keywords)
        current_keywords = initial_keywords

        for i in range(max_retries + 1):  # +1 for the initial attempt
            print_info(f"[第 {i+1}/{max_retries+1} 轮] 为场景 \"{scene['text'][:20]}...\" 搜索 {num_assets} 个素材")
            print_info(f"  -> 使用关键词: {current_keywords}")

            found_assets = self._find_assets_with_keywords(current_keywords, num_assets)
            
            if len(found_assets) >= num_assets:
                print_info(f"成功！为该场景找到 {len(found_assets)} 个素材。")
                return found_assets
            
            log.warning(f"查找失败，只找到 {len(found_assets)}/{num_assets} 个素材。")

            if i < max_retries:
                print_info("准备生成新关键词并重试...")
                new_keywords = self._generate_new_keywords(scene['text'], tried_keywords)
                if not new_keywords:
                    log.warning("Ollama未能生成有效的新关键词。停止此场景的搜索。")
                    break  # 如果Ollama失败，则停止重试
                
                current_keywords = new_keywords
                tried_keywords.update(kw.lower() for kw in new_keywords)
            else:
                log.warning("已达到最大重试次数，停止搜索。")

        return []  # 所有尝试都失败后返回空列表

    def _search_online(self, keywords: list, num_to_find: int) -> List[str]:
        if not keywords or not self.pexels_api_key or "YOUR_PEXELS_API_KEY_HERE" in self.pexels_api_key:
            return []
        
        query = " ".join(keywords)
        print_info(f"正在 Pexels 在线搜索: '{query}' (需要 {num_to_find} 个)")
        
        try:
            headers = {"Authorization": self.pexels_api_key}
            # 请求更多视频以增加随机性
            per_page = num_to_find * 2 if num_to_find > 1 else 5
            url = f"https://api.pexels.com/videos/search?query={query}&per_page={per_page}&orientation=landscape"
            
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            
            videos = res.json().get("videos", [])
            if not videos:
                log.warning(f"Pexels 未找到关于 '{query}' 的视频。")
                return []

            # 随机选择所需数量的视频
            num_to_select = min(num_to_find, len(videos))
            selected_videos = random.sample(videos, num_to_select)
            
            downloaded_paths = []
            for video in selected_videos:
                video_id = video.get('id')
                if not video_id:
                    log.warning("Pexels返回的视频数据中缺少ID，无法缓存。")
                    continue
                
                # 检查数据库中是否已存在此视频
                existing_path = self.db_manager.find_asset_by_source_id('pexels', str(video_id))
                if existing_path:
                    print_info(f"在本地缓存中找到素材 (来自数据库): pexels_{video_id}.mp4")
                    downloaded_paths.append(existing_path)
                    continue

                # 如果不在缓存中，则下载并保存到日期子目录
                video_files = video.get("video_files", [])
                video_link = next((v['link'] for v in video_files if 'hd' in v['quality']), None)
                if not video_link:
                    video_link = video_files[0]['link'] if video_files else None
                if not video_link:
                    continue

                # 创建日期子目录
                today_str = datetime.date.today().strftime("%Y-%m-%d")
                daily_dir = os.path.join(self.local_assets_path, today_str)
                os.makedirs(daily_dir, exist_ok=True)
                
                filename = f"pexels_{video_id}.mp4"
                local_file_path = os.path.join(daily_dir, filename)

                try:
                    print_info(f"正在下载新素材: {filename}")
                    video_res = requests.get(video_link, timeout=60, stream=True)
                    video_res.raise_for_status()

                    with open(local_file_path, 'wb') as f:
                        for chunk in video_res.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    # 下载成功后，注册到数据库
                    self.db_manager.add_asset('pexels', str(video_id), keywords, local_file_path)
                    print_info(f"视频已下载并索引: {local_file_path}")
                    downloaded_paths.append(local_file_path)
                except Exception as download_e:
                    log.error(f"下载视频 {video_id} 失败: {download_e}", exc_info=True)
                    # 如果下载失败，清理可能已创建的不完整文件
                    if os.path.exists(local_file_path):
                        os.remove(local_file_path)
                    continue
            
            return downloaded_paths

        except requests.exceptions.RequestException as e:
            log.error(f"Pexels API 请求失败: {e}", exc_info=True)
            return []
        except Exception as e:
            log.error(f"在线搜索或下载过程中发生未知错误: {e}", exc_info=True)
            return []