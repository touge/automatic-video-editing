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
        self.models = self.config.get('models', [])
        self.default_model = self.models[0] if self.models else None
        self.default_speaker = self.config.get('default_speaker')

        if not self.api_key:
            raise ValueError("SiliconFlow TTS provider config must contain an 'api_key'.")
        if not self.default_model:
            raise ValueError("SiliconFlow TTS provider config must contain a 'models' list.")
        if not self.default_speaker:
            raise ValueError("SiliconFlow TTS provider config must contain a 'default_speaker'.")

    def synthesize(self, text: str, task_id: str, **kwargs) -> Dict:
        """
        Synthesize speech using the SiliconFlow TTS service.
        """
        task_manager = TaskManager(task_id)
        full_api_url = f"{self.host}/v1/audio/speech"
        
        headers = {
            'Authorization': f"Bearer {self.api_key}",
            'Content-Type': 'application/json',
            'Accept': 'audio/wav' # 请求 WAV 格式以便处理
        }

        speaker = kwargs.get('speaker', self.default_speaker)
        model = kwargs.get('model', self.default_model)
        speed = kwargs.get('speed', 1.0)
        
        # SiliconFlow 的 voice 参数格式为 "model_name:speaker_name"
        voice_param = f"{model}:{speaker}"

        payload = {
            "model": model,
            "input": text,
            "voice": voice_param,
            "speed": speed,
            "response_format": "wav" # 请求 WAV 格式
        }

        try:
            log.info(f"Sending TTS request to SiliconFlow with speaker '{speaker}'")
            response = requests.post(full_api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            
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
