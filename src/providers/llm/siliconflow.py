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
        self.model = self.config.get('model') # Expect a single model string

        if not self.api_key:
            raise ValueError("SiliconFlow provider config must contain an 'api_key'.")
        if not self.host:
            raise ValueError("SiliconFlow provider config must contain a 'host'.")
        if not self.model: # Check for single model field
            raise ValueError("SiliconFlow provider config must contain a 'model' field.")

        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.host)
            self.default_model = self.model # The single model is the default
        except Exception as e:
            raise ConnectionError(f"Failed to configure SiliconFlow client: {e}")

    def generate(self, prompt: str, **kwargs) -> str:
        """
        使用SiliconFlow生成文本。
        此实现直接调用 completion API，并过滤掉不支持的参数。
        """
        model = kwargs.pop('model', self.default_model)
        if model != self.model:
            raise ValueError(f"Model '{model}' is not the configured model for provider '{self.name}'. Configured model: {self.model}")

        # 仅传递 'temperature' 和 'max_tokens' 等有效参数
        supported_params = ['temperature', 'max_tokens', 'top_p', 'top_k', 'stop']
        generation_kwargs = {k: v for k, v in kwargs.items() if k in supported_params}

        try:
            messages = [{"role": "user", "content": prompt}]
            completion = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **generation_kwargs
            )
            return completion.choices[0].message.content
        except Exception as e:
            log.error(f"SiliconFlow generation failed: {e}", exc_info=True)
            raise

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        使用SiliconFlow进行聊天，并过滤掉不支持的参数。
        """
        model = kwargs.pop('model', self.default_model)
        if model != self.model:
            raise ValueError(f"Model '{model}' is not the configured model for provider '{self.name}'. Configured model: {self.model}")
            
        supported_params = ['temperature', 'max_tokens', 'top_p', 'top_k', 'stop']
        chat_kwargs = {k: v for k, v in kwargs.items() if k in supported_params}

        try:
            completion = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **chat_kwargs
            )
            return completion.choices[0].message.content
        except Exception as e:
            log.error(f"SiliconFlow chat failed: {e}", exc_info=True)
            raise
