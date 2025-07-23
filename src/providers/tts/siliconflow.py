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
        self.endpoint = self.config.get('endpoint', 'https://api.siliconflow.cn').rstrip('/')
        self.model = self.config.get('model')
        self.speed = self.config.get('speed', 1.0) # 默认值
        self.sample_rate = self.config.get('sample_rate', 16000) # 新增
        self.stream = self.config.get('stream', False) # 新增

        if not self.api_key:
            raise ValueError("SiliconFlow TTS provider config must contain an 'api_key'.")
        if not self.model:
            raise ValueError("SiliconFlow TTS provider config must contain a 'model'.")
        
        if 'speakers' not in self.config or not isinstance(self.config['speakers'], dict):
            log.warning("SiliconFlow TTS provider config should contain a 'speakers' dictionary.")

    def synthesize(self, text: str, task_id: str, **kwargs) -> Dict:
        """
        Synthesize speech using the SiliconFlow TTS service.
        """
        is_test = kwargs.get('is_test', False)
        if is_test and not task_id: # In test mode, task_id can be None
            pass
        elif not task_id:
            raise ValueError("A valid task_id is required for synthesis.")
        
        full_api_url = f"{self.endpoint}/v1/audio/speech"
        
        headers = {
            'Authorization': f"Bearer {self.api_key}",
            'Content-Type': 'application/json',
            'Accept': 'audio/wav' # 请求 WAV 格式以便处理
        }

        # Use configured speaker unless overridden in kwargs
        speaker = kwargs.get('speaker')
        if not speaker:
            raise ValueError("'speaker' must be provided in kwargs for synthesize method.")
        # Model is fixed from config
        model = self.model
        # Use configured speed unless overridden in kwargs
        speed = kwargs.get('speed', self.speed)

        # SiliconFlow's voice parameter format is "model_name:speaker_name"
        # 根据 config.yaml，speaker 字段本身就是完整的 voice 参数
        # voice_param = f"{model}:{speaker}" # 移除此行

        payload = {
            "model": model,
            "input": text,
            "voice": speaker, # 直接使用 speaker 字段作为 voice 参数
            "speed": speed,
            "response_format": "wav", # 请求 WAV 格式
            "sample_rate": kwargs.get('sample_rate', self.sample_rate), # 新增
            "stream": kwargs.get('stream', self.stream) # 新增
        }

        def _do_request():
            """封装实际的请求逻辑，供重试机制调用。"""
            if not is_test:
                log.info(f"Sending TTS request to SiliconFlow with speaker '{speaker}'")
            
            response = requests.post(full_api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            return response

        try:
            response = self._execute_with_retry(_do_request)

            # If it's a test call, we don't need to save the file, just return success.
            if is_test:
                return {'status': 'ok', 'path': None}

            # --- Regular synthesis file saving logic ---
            task_manager = TaskManager(task_id)
            # 生成一个基于文本内容的哈希作为文件名，以实现缓存
            text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
            
            # 清理 speaker 名称中的非法字符，特别是冒号
            cleaned_speaker = speaker.replace(':', '_').replace('/', '_').replace('\\', '_')
            output_path = task_manager.get_file_path('tts_audio', name=f"{cleaned_speaker}_{text_hash}")

            # 将二进制音频内容写入文件
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            log.info(f"TTS synthesis successful. Audio saved to: {output_path}")
            return {'status': 'ok', 'path': output_path}

        except Exception as e:
            # _execute_with_retry 已经处理了重试和日志，这里只捕获最终的失败
            log.error(f"Final attempt for SiliconFlow TTS synthesis failed: {e}")
            raise
