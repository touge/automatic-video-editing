import requests
import os
from typing import List, Dict, Any
from pathlib import Path
from .base import BaseVideoProvider
from src.logger import log

class AiSearchProvider(BaseVideoProvider):
    """
    通过AI API搜索视频的提供者。
    """
    def __init__(self, config: dict):
        ai_search_config = config.get('ai_search', {})
        self.api_key = ai_search_config.get('api_key')
        self.api_url = ai_search_config.get('api_url')
        if not self.api_key or not self.api_url:
            raise ValueError("AI Search API key or URL not found in config.yaml under 'ai_search'")
        self.enabled = True

    def search(self, keywords: List[str], count: int = 1) -> List[Dict[str, Any]]:
        """
        使用AI API搜索本地视频。
        """
        if not self.enabled:
            log.info("AI Search provider is disabled due to a previous connection error. Skipping.")
            return []
        query = " ".join(keywords)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

# 📥 接收到请求 data.dict():
# {'top_n': 8, 'positive': 'avoiding fatty foods', 'negative': '', 'positive_threshold': 35.0, 'negative_threshold': 35.0, 'image_threshold': 0.9, 'img_id': '', 'path': '', 'start_time': 0, 'end_time': 0}
# 2025-07-05 15:22:00,446 logic.search_logic INFO 视频查询耗时：0.22 秒
# INFO:     192.168.0.168:61662 - "POST /api/videos/text HTTP/1.1" 200 OK
# 📥 接收到请求 data.dict():
# {'top_n': 15, 'positive': '', 'negative': '', 'positive_threshold': 35.0, 'negative_threshold': 35.0, 'image_threshold': 0.9, 'img_id': '', 'path': '', 'start_time': 0, 'end_time': 0}
        # 这是一个示例请求体，请根据您的API进行修改
        payload = {
            "positive": query,
            "top_n": count,
            "positive_threshold": 35,
            "negative_threshold": 35
        }
        
        try:
            log.debug(f"向AI搜索API发送请求: URL={self.api_url}, Payload={payload}")
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            # print(f"data:{data}")
            # API返回一个包含 'results' 键的字典，我们将该键下的列表传递给验证函数
            return self._standardize_results(data.get('results', []))
        except requests.RequestException as e:
            # 捕获所有 requests 相关的异常，包括连接、超时和HTTP错误
            self.enabled = False # 禁用此提供者
            
            error_message = f"AI Search provider '{self.api_url}' failed"
            if hasattr(e, 'response') and e.response is not None:
                error_message += f" with status code {e.response.status_code}."
            else:
                error_message += f" with a connection error: {e.__class__.__name__}."
            
            log.error(f"{error_message} It will be disabled for the rest of this session.")
            return []

    def _standardize_results(self, videos: List[Dict]) -> List[Dict[str, Any]]:
        """
        验证AI API的返回结果。
        API应返回一个字典列表，每个字典代表一个视频，且已包含标准化键。
        此函数主要验证每个结果中的文件路径是否存在。
        """
        validated_videos = []
        for video_info in videos:
            # API返回的应该是字典
            if not isinstance(video_info, dict):
                log.warning(f"AI search returned an invalid item (expected a dict): {video_info}")
                continue
            
            # 从字典中获取 'download_url'，它应该是本地路径
            local_path_str = video_info.get('download_url')
            if not local_path_str:
                log.warning(f"AI search result item is missing 'download_url' key: {video_info}")
                continue

            local_path = Path(local_path_str)
            
            if not local_path.exists():
                log.warning(f"AI search returned a non-existent file path: {local_path}")
                continue

            # 路径有效，将此视频信息添加到结果列表
            validated_videos.append(video_info)
            
        return validated_videos