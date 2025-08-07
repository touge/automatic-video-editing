import requests
from typing import Optional, Dict, Any
from .base import DigitalHumanProvider

class HeygemProvider(DigitalHumanProvider):
    def __init__(self, endpoint: str, token: str):
        self.endpoint = endpoint
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

    def generate_video(self, audio_file_path: str, character_name: str, segments_json: Optional[str] = None) -> Dict[str, Any]:
        with open(audio_file_path, "rb") as audio_file:
            files = {"audio_file": audio_file}
            data = {"character_name": character_name}
            if segments_json:
                data["segments_json"] = segments_json

            # 明确禁用代理，以避免在调用内网服务时出现 "Privoxy" 等代理错误
            # 这与 IndexTtsProvider 和其他内网服务的处理方式保持一致
            proxies = {
               "http": None,
               "https": None,
            }
            response = requests.post(self.endpoint, headers=self.headers, files=files, data=data, proxies=proxies)
            response.raise_for_status()
            return response.json()
