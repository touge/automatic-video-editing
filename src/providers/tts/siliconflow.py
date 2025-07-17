import requests
import hashlib
from .base import BaseTtsProvider
from src.logger import log
from src.core.task_manager import TaskManager
from typing import Dict

class SiliconflowTtsProvider(BaseTtsProvider):
    """
    A TTS provider for SiliconFlow.
    """
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.api_key = self.config.get('api_key')
        self.host = self.config.get('host', 'https://api.siliconflow.cn').rstrip('/')
        self.model = self.config.get('model')
        self.speaker = self.config.get('speaker')

        if not self.api_key:
            raise ValueError("SiliconFlow TTS provider config must contain an 'api_key'.")
        if not self.model:
            raise ValueError("SiliconFlow TTS provider config must contain a 'model'.")
        if not self.speaker:
            raise ValueError("SiliconFlow TTS provider config must contain a 'speaker'.")

    def synthesize(self, text: str, task_id: str, **kwargs) -> Dict:
        """
        Synthesize speech using the SiliconFlow TTS service.
        """
        is_test = kwargs.get('is_test', False)
        if is_test and not task_id: # In test mode, task_id can be None
            pass
        elif not task_id:
            raise ValueError("A valid task_id is required for synthesis.")
        
        full_api_url = f"{self.host}/v1/audio/speech"
        
        headers = {
            'Authorization': f"Bearer {self.api_key}",
            'Content-Type': 'application/json',
            'Accept': 'audio/wav' # 请求 WAV 格式以便处理
        }

        # Use configured speaker unless overridden in kwargs
        speaker = kwargs.get('speaker', self.speaker)
        # Model is fixed from config
        model = self.model
        speed = kwargs.get('speed', 1.0)

        # SiliconFlow's voice parameter format is "model_name:speaker_name"
        voice_param = f"{model}:{speaker}"

        payload = {
            "model": model,
            "input": text,
            "voice": voice_param,
            "speed": speed,
            "response_format": "wav" # 请求 WAV 格式
        }

        try:
            if not is_test:
                log.info(f"Sending TTS request to SiliconFlow with speaker '{speaker}'")
            
            response = requests.post(full_api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()

            # If it's a test call, we don't need to save the file, just return success.
            if is_test:
                return {'status': 'ok', 'path': None}

            # --- Regular synthesis file saving logic ---
            task_manager = TaskManager(task_id)
            # 生成一个基于文本内容的哈希作为文件名，以实现缓存
            text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
            output_path = task_manager.get_file_path('tts_audio', name=f"{speaker}_{text_hash}")

            # 将二进制音频内容写入文件
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            log.info(f"TTS synthesis successful. Audio saved to: {output_path}")
            return {'status': 'ok', 'path': output_path}

        except requests.exceptions.RequestException as e:
            log.error(f"Failed to connect to SiliconFlow TTS service at {full_api_url}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                log.error(f"Response body: {e.response.text}")
            raise
        except Exception as e:
            log.error(f"An unexpected error occurred during SiliconFlow TTS synthesis: {e}")
            raise
