import requests
import base64
import os
from .base import BaseTtsProvider
from src.logger import log
from typing import Dict
from src.core.task_manager import TaskManager

class IndexTtsProvider(BaseTtsProvider):
    """
    A TTS provider for IndexTTS that works via an HTTP POST request.
    This provider handles a JSON response containing base64 encoded audio data.
    """
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.endpoint = self.config.get('endpoint', '').rstrip('/')
        self.api_key = self.config.get('api_key')
        self.speed = self.config.get('speed', 1.0)
        self.volume = self.config.get('volume', 0)
        self.api_path = "/api/v2/tts"

        if not self.endpoint:
            raise ValueError("IndexTTS provider config must contain an 'endpoint'.")
        if not self.api_key:
            raise ValueError("IndexTTS provider config must contain an 'api_key'.")

    def synthesize(self, text: str, task_id: str, **kwargs) -> Dict:
        """
        Synthesize speech using the IndexTTS service.
        """
        if not task_id:
            raise ValueError("A valid task_id is required for synthesis.")

        full_api_url = self.endpoint + self.api_path

        headers = {
            'accept': 'application/json',
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        speaker_id = kwargs.get('speaker_id', "")
        speed = kwargs.get('speed', self.speed)
        volume = kwargs.get('volume', self.volume)

        payload = {
            "text": text,
            "speaker_id": speaker_id,
            "speed": speed,
            "volume": volume
        }

        def _do_request():
            log.info(f"Sending TTS request to {full_api_url} with speaker_id '{speaker_id}'")
            proxies = {"http": None, "https": None}
            response = requests.post(full_api_url, headers=headers, json=payload, proxies=proxies)
            response.raise_for_status()
            return response.json()

        try:
            data = self._execute_with_retry(_do_request)
            
            if 'data' in data and data['data']:
                audio_data = base64.b64decode(data['data'])
                
                # Use TaskManager to get the correct temporary cache path
                task_manager = TaskManager(task_id)
                # We create a temporary file inside the task's own .audios directory
                temp_dir = os.path.dirname(task_manager.get_file_path('audio_segment', index=0))
                os.makedirs(temp_dir, exist_ok=True)
                
                # Create a unique temporary filename
                temp_filename = f"temp_{os.urandom(16).hex()}.wav"
                temp_filepath = os.path.join(temp_dir, temp_filename)

                with open(temp_filepath, 'wb') as f:
                    f.write(audio_data)
                
                log.info(f"Decoded base64 audio and saved to task's cache: {temp_filepath}")
                
                return {'status': 'ok', 'path': temp_filepath}
            
            elif 'url' in data and data['url']:
                log.info(f"TTS API returned a URL: {data['url']}")
                return {'status': 'ok', 'url': data['url']}
            else:
                log.error(f"TTS response is missing 'data' or 'url' key: {data}")
                raise Exception("Invalid TTS API response format.")

        except Exception as e:
            log.error(f"Final attempt for IndexTTS synthesis failed: {e}")
            raise
