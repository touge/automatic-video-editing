from openai import OpenAI
from .base import BaseLlmProvider
from src.logger import log
from typing import List, Dict

class SiliconflowProvider(BaseLlmProvider):
    """
    硅基流动 (SiliconFlow) LLM 提供者。
    该提供商的API与OpenAI兼容。
    """
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.api_key = self.config.get('api_key')
        self.host = self.config.get('host')
        self.model_name = self.config.get('model')

        if not self.api_key:
            raise ValueError("SiliconFlow provider config must contain an 'api_key'.")
        if not self.host:
            raise ValueError("SiliconFlow provider config must contain a 'host'.")
        if not self.model_name:
            raise ValueError("SiliconFlow provider config must contain a 'model'.")

        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.host)
        except Exception as e:
            raise ConnectionError(f"Failed to configure SiliconFlow client: {e}")

    def generate(self, prompt: str, **kwargs) -> str:
        """
        使用SiliconFlow生成文本。
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, **kwargs)

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        使用SiliconFlow进行聊天。
        """
        try:
            completion = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                **kwargs
            )
            return completion.choices[0].message.content
        except Exception as e:
            log.error(f"An unexpected error occurred with SiliconFlow (chat): {e}")
            raise