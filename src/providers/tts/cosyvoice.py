import requests
from .base import BaseTtsProvider
from src.logger import log
from typing import Dict

class CosyVoiceTtsProvider(BaseTtsProvider):
    """
    A TTS provider for CosyVoice that works via an HTTP POST request.
    """
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.endpoint = self.config.get('endpoint', '').rstrip('/')
        self.api_key = self.config.get('api_key')
        self.speed = self.config.get('speed', 0.95) # Provide a default speed
        self.api_path = "/speak_as"  # Hardcoded API path for this provider
        
        if not self.endpoint:
            raise ValueError("CosyVoice TTS provider config must contain a 'endpoint'.")
        
        # The 'speakers' dictionary is now validated in AudioGenerator, not here.
        if 'speakers' not in self.config or not isinstance(self.config['speakers'], dict):
             log.warning("CosyVoice TTS provider config should contain a 'speakers' dictionary.")

    def synthesize(self, text: str, task_id: str, **kwargs) -> Dict:
        """
        Synthesize speech using the CosyVoice TTS service.
        The 'task_id' is ignored by this provider but required by the base class.
        """
        is_test = kwargs.get('is_test', False)
        if is_test and not task_id: # In test mode, task_id can be None
            pass
        elif not task_id:
            raise ValueError("A valid task_id is required for synthesis.")

        full_api_url = self.endpoint + self.api_path
        
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json'
        }
        if self.api_key:
            headers['x-api-key'] = self.api_key

        speaker = kwargs.get('speaker')
        if not speaker:
            raise ValueError("'speaker' must be provided in kwargs for synthesize method.")
            
        return_type = kwargs.get('return_type', 'url')
        # speed = kwargs.get('speed', 0.95)
        speed = kwargs.get('speed', self.speed)

        payload = {
            "speaker": speaker,
            "text": text,
            "return_type": return_type,
            "speed": speed
        }

        def _do_request():
            """封装实际的请求逻辑，供重试机制调用。"""
            if not is_test:
                log.info(f"Sending TTS request to {full_api_url} with speaker '{speaker}'")
            
            # 显式禁用代理，以解决本地网络中 Privoxy 等代理服务器的干扰问题
            proxies = {
                "http": None,
                "https": None,
            }
            
            response = requests.post(full_api_url, headers=headers, json=payload, proxies=proxies)
            response.raise_for_status()
            return response.json() # 返回 JSON 响应

        try:
            data = self._execute_with_retry(_do_request)
            
            # If it's a test call, we just need to know it succeeded.
            if is_test:
                return {'status': 'ok'}

            if data.get('status') == 'ok':
                # Assemble the full URL if the response is a relative path
                audio_url = data.get('url', '')
                if not audio_url.startswith(('http://', 'https://')):
                    audio_url = self.endpoint + audio_url
                data['url'] = audio_url
                log.info(f"TTS synthesis successful. Full audio URL: {audio_url}")
                return data
            else:
                log.error(f"TTS synthesis failed with status: {data.get('status')}. Reason: {data.get('message')}")
                raise Exception(f"TTS API returned an error: {data.get('message')}")

        except Exception as e:
            # _execute_with_retry 已经处理了重试和日志，这里只捕获最终的失败
            log.error(f"Final attempt for CosyVoice TTS synthesis failed: {e}")
            raise
