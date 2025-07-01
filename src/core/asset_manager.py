import os
import requests
import random
import datetime
from typing import List
from .database_manager import DatabaseManager

class AssetManager:
    def __init__(self, config: dict, task_id: str):
        self.config = config
        self.task_id = task_id
        self.local_assets_path = config.get('paths', {}).get('local_assets_dir', 'assets/local')
        self.pexels_api_key = config.get('pexels', {}).get('api_key', '')
        # 初始化数据库管理器
        self.db_manager = DatabaseManager()
        os.makedirs(self.local_assets_path, exist_ok=True)

    def find_assets_for_scene(self, scene: dict, num_assets: int) -> List[str]:
        """
        为单个场景查找指定数量的素材。
        会先在本地搜索，如果不足，再从Pexels在线查找补充。
        """
        keywords = scene.get('keywords_en', [])
        if not keywords:
            print("警告: 场景没有关键词，无法搜索素材。")
            return []
        
        print(f"为场景 \"{scene['text'][:20]}...\" 搜索 {num_assets} 个素材，关键词: {keywords}")

        # 1. 在本地数据库中搜索
        local_found = self.db_manager.find_assets_by_keywords(keywords, num_assets)
        
        # 2. 如果本地素材不足，在线搜索补充
        remaining_needed = num_assets - len(local_found)
        if remaining_needed > 0:
            print(f"本地找到 {len(local_found)} 个，仍需在线搜索 {remaining_needed} 个。")
            online_found = self._search_online(keywords, remaining_needed)
            return local_found + online_found
        else:
            print(f"在本地数据库中找到 {len(local_found)} 个素材。")
            return local_found

    def _search_online(self, keywords: list, num_to_find: int) -> List[str]:
        if not keywords or not self.pexels_api_key or "YOUR_PEXELS_API_KEY_HERE" in self.pexels_api_key:
            return []
        
        query = " ".join(keywords)
        print(f"正在 Pexels 在线搜索: {query} (需要 {num_to_find} 个)")
        
        try:
            headers = {"Authorization": self.pexels_api_key}
            # 请求更多视频以增加随机性
            per_page = num_to_find * 2 if num_to_find > 1 else 5
            url = f"https://api.pexels.com/videos/search?query={query}&per_page={per_page}&orientation=landscape"
            
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            
            videos = res.json().get("videos", [])
            if not videos:
                print(f"Pexels 未找到关于 '{query}' 的视频。")
                return []

            # 随机选择所需数量的视频
            num_to_select = min(num_to_find, len(videos))
            selected_videos = random.sample(videos, num_to_select)
            
            downloaded_paths = []
            for video in selected_videos:
                video_id = video.get('id')
                if not video_id:
                    print("警告: Pexels返回的视频数据中缺少ID，无法缓存。")
                    continue
                
                # 检查数据库中是否已存在此视频
                existing_path = self.db_manager.find_asset_by_source_id('pexels', str(video_id))
                if existing_path:
                    print(f"在本地缓存中找到素材 (来自数据库): pexels_{video_id}.mp4")
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
                    print(f"正在下载新素材: {filename}")
                    video_res = requests.get(video_link, timeout=60, stream=True)
                    video_res.raise_for_status()

                    with open(local_file_path, 'wb') as f:
                        for chunk in video_res.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    # 下载成功后，注册到数据库
                    self.db_manager.add_asset('pexels', str(video_id), keywords, local_file_path)
                    print(f"视频已下载并索引: {local_file_path}")
                    downloaded_paths.append(local_file_path)
                except Exception as download_e:
                    print(f"下载视频 {video_id} 失败: {download_e}")
                    # 如果下载失败，清理可能已创建的不完整文件
                    if os.path.exists(local_file_path):
                        os.remove(local_file_path)
                    continue
            
            return downloaded_paths

        except requests.exceptions.RequestException as e:
            print(f"Pexels API 请求失败: {e}")
            return []
        except Exception as e:
            print(f"在线搜索或下载过程中发生未知错误: {e}")
            return []