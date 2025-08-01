import requests
import sys
from typing import List, Dict, Any
from .base import BaseVideoProvider
from src.logger import log

class PexelsProvider(BaseVideoProvider):
    """
    从 Pexels.com 搜索和下载视频的提供者。
    """
    def __init__(self, config: dict):
        super().__init__()
        pexels_config = config.get('search_providers', {}).get('pexels', {})
        self.api_key = pexels_config.get('api_key')
        api_host = pexels_config.get('api_host', 'https://api.pexels.com')
        if not self.api_key:
            raise ValueError("Pexels API key not found in config.yaml under 'search_providers.pexels'")
        self.api_url = f"{api_host.rstrip('/')}/videos/search"
        self.enabled = pexels_config.get('enabled', False)

    def search(self, keywords: List[str], count: int = 1, min_duration: float = 0) -> List[Dict[str, Any]]:
        """
        在 Pexels 上搜索视频。
        在这里你可以轻松修改搜索参数，例如 'orientation', 'size' 等。
        """
        if not self.enabled:
            return []
            
        query = " ".join(keywords)
        headers = {"Authorization": self.api_key}
        params = {
            "query": query,
            "per_page": count,
            "orientation": "landscape",  # 在这里修改，例如 'portrait' 或 'square'
            "size": "medium"             # 在这里修改，例如 'large' 或 'small'
        }
        
        try:
            response = requests.get(self.api_url, headers=headers, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()
            return self._standardize_results(data.get('videos', []))
        except requests.RequestException as e:
            self.enabled = False
            error_message = f"Pexels provider failed"
            if hasattr(e, 'response') and e.response is not None:
                error_message += f" with status code {e.response.status_code}."
            else:
                error_message += f" with a connection error: {e.__class__.__name__}."
            log.error(f"{error_message} It will be disabled for the rest of this session.")
            return []
        except KeyboardInterrupt:
            log.error("用户中断了操作。")
            sys.exit(0)

    def _standardize_results(self, videos: List[Dict]) -> List[Dict[str, Any]]:
        """将 Pexels API 的返回结果标准化。"""
        import os
        from urllib.parse import urlparse

        standardized_videos = []
        for video in videos:
            video_file = max(video.get('video_files', []), key=lambda x: x.get('width', 0))
            if video_file:
                download_url = video_file['link']
                try:
                    # 从URL中提取文件名作为video_name
                    path = urlparse(download_url).path
                    video_name = os.path.basename(path)
                except Exception:
                    video_name = f"pexels-{video['id']}.mp4" # 后备方案

                standardized_videos.append({
                    'id': f"pexels-{video['id']}",
                    'video_name': video_name,
                    'download_url': download_url,
                    'source': 'pexels',
                    'description': f"Video by {video['user']['name']} on Pexels"
                })
        return standardized_videos
