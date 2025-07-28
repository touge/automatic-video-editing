import requests
import os
import sys
from typing import List, Dict, Any
from pathlib import Path
from urllib.parse import urlparse
from .base import BaseVideoProvider
from src.logger import log

class AiSearchProvider(BaseVideoProvider):
    """
    通过AI API搜索视频的提供者。
    """
    def __init__(self, config: dict):
        super().__init__()
        ai_search_config = config.get('search_providers', {}).get('ai_search', {})
        self.api_key = ai_search_config.get('api_key')
        self.api_url = ai_search_config.get('api_url')
        if not self.api_key or not self.api_url:
            raise ValueError("AI Search API key or URL not found in config.yaml under 'search_providers.ai_search'")
        self.enabled = ai_search_config.get('enabled', False)

    def search(self, keywords: List[str], count: int = 1, min_duration: float = 0) -> List[Dict[str, Any]]:
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
            "positive_threshold": 25,
            "negative_threshold": 25,
            "min_duration": min_duration
        }
        
        try:
            log.debug(f"向AI搜索API发送请求: URL={self.api_url}, Payload={payload}")
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            return self._standardize_results(data.get('results', []))
        except requests.RequestException as e:
            self.enabled = False
            error_message = f"AI Search provider '{self.api_url}' failed"
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
        """
        验证AI API的返回结果，并将其标准化以进行重复数据删除。
        - 使用 'video_id' 和 'video_name' 创建一个唯一的稳定ID。
        - 将此稳定ID覆盖 'id' 字段。
        """
        standardized_videos = []
        seen_ids = set()

        for video_info in videos:
            if not isinstance(video_info, dict):
                log.warning(f"AI search returned an invalid item (expected a dict): {video_info}")
                continue

            video_id = video_info.get('video_id')
            video_name = video_info.get('video_name')

            if not video_id or not video_name:
                log.warning(f"AI search result item is missing 'video_id' or 'video_name': {video_info}")
                continue

            # 使用 video_id 和 video_name 创建唯一ID
            stable_id = f"ai-{video_id}-{video_name}"
            video_info['id'] = stable_id

            # 检查此稳定ID是否已被处理
            if video_info['id'] in seen_ids:
                log.debug(f"Skipping duplicate video with stable ID: {video_info['id']}")
                continue
            
            # 检查并提取视频时长
            duration_str = video_info.get('duration')
            if duration_str and isinstance(duration_str, str) and duration_str.endswith('s'):
                try:
                    video_info['duration'] = float(duration_str[:-1])
                except (ValueError, TypeError):
                    log.warning(f"AI search result for '{video_info['id']}' has invalid duration: {duration_str}. Skipping duration.")
                    video_info.pop('duration', None)
            elif isinstance(duration_str, (int, float)):
                video_info['duration'] = float(duration_str)
            else:
                if duration_str is not None:
                    log.warning(f"AI search result for '{video_info['id']}' has unexpected duration format: {duration_str}. Skipping.")
                video_info.pop('duration', None)

            standardized_videos.append(video_info)
            seen_ids.add(video_info['id'])

        return standardized_videos
