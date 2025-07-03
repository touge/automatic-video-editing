import requests
from typing import List, Dict, Any
from .base import BaseVideoProvider

class PexelsProvider(BaseVideoProvider):
    """
    从 Pexels.com 搜索和下载视频的提供者。
    """
    def __init__(self, config: dict):
        pexels_config = config.get('pexels', {})
        self.api_key = pexels_config.get('api_key')
        api_host = pexels_config.get('api_host', 'https://api.pexels.com')
        if not self.api_key:
            raise ValueError("Pexels API key not found in config.yaml")
        self.api_url = f"{api_host.rstrip('/')}/videos/search"

    def search(self, keywords: List[str], count: int = 1) -> List[Dict[str, Any]]:
        """
        在 Pexels 上搜索视频。
        在这里你可以轻松修改搜索参数，例如 'orientation', 'size' 等。
        """
        query = " ".join(keywords)
        headers = {"Authorization": self.api_key}
        params = {
            "query": query,
            "per_page": count,
            "orientation": "landscape",  # 在这里修改，例如 'portrait' 或 'square'
            "size": "medium"             # 在这里修改，例如 'large' 或 'small'
        }
        
        try:
            response = requests.get(self.api_url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            return self._standardize_results(data.get('videos', []))
        except requests.RequestException as e:
            print(f"Error searching Pexels for '{query}': {e}")
            return []

    def _standardize_results(self, videos: List[Dict]) -> List[Dict[str, Any]]:
        """将 Pexels API 的返回结果标准化。"""
        standardized_videos = []
        for video in videos:
            video_file = max(video.get('video_files', []), key=lambda x: x.get('width', 0))
            if video_file:
                standardized_videos.append({
                    'id': f"pexels-{video['id']}",
                    'download_url': video_file['link'],
                    'source': 'pexels',
                    'description': f"Video by {video['user']['name']} on Pexels"
                })
        return standardized_videos