import requests
from typing import List, Dict, Any
from .base import BaseVideoProvider
from src.logger import log

class PixabayProvider(BaseVideoProvider):
    def __init__(self, config: dict):
        super().__init__()
        pixabay_config = config.get('pixabay', {})
        self.api_key = pixabay_config.get('api_key')
        api_host = pixabay_config.get('api_host', 'https://pixabay.com')
        if not self.api_key:
            raise ValueError("Pixabay API key not found in config.yaml")
        self.api_url = f"{api_host.rstrip('/')}/api/videos/"

    def search(self, keywords: List[str], count: int = 1) -> List[Dict[str, Any]]:
        """
        在 Pixabay 上搜索视频。
        """
        if not self.enabled:
            return []
            
        # Pixabay API 使用 '+' 连接关键词
        query = "+".join(keywords)
        params = {
            "key": self.api_key,
            "q": query,
            "per_page": count,
            "video_type": "film",
            "orientation": "horizontal",
            "safesearch": "true"
        }
        
        try:
            response = requests.get(self.api_url, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()
            return self._standardize_results(data.get('hits', []))
        except requests.RequestException as e:
            self.enabled = False
            error_message = f"Pixabay provider failed"
            if hasattr(e, 'response') and e.response is not None:
                error_message += f" with status code {e.response.status_code}."
            else:
                error_message += f" with a connection error: {e.__class__.__name__}."
            log.error(f"{error_message} It will be disabled for the rest of this session.")
            return []

    def _standardize_results(self, videos: List[Dict]) -> List[Dict[str, Any]]:
        """将 Pixabay API 的返回结果标准化。"""
        standardized_videos = []
        for video in videos:
            # Pixabay 的 'videos' 是一个字典，'large' 或 'medium' 通常是最佳选择
            video_files = video.get('videos', {})
            best_video = video_files.get('large', video_files.get('medium', {}))
            
            if best_video and 'url' in best_video:
                standardized_videos.append({
                    'id': f"pixabay-{video['id']}",
                    'download_url': best_video['url'],
                    'source': 'pixabay',
                    'description': f"Video by {video.get('user', 'Unknown User')} on Pixabay"
                })
        return standardized_videos
