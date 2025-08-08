import openai
import os
from .base import BaseLlmProvider
from typing import List, Dict

class GeminiProvider(BaseLlmProvider):
    """
    OpenAI LLM Provider.
    """
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.api_key = self.config.get('api_key')
        self.base_url = self.config.get('base_url')
        self.model = self.config.get('model')
        self.timeout = self.config.get('timeout')

        if not self.api_key:
            raise ValueError("OpenAI provider config must contain an 'api_key'.")
        if not self.model:
            raise ValueError("OpenAI provider config must contain a 'model' field.")
        
        # 恢复到使用环境变量禁用代理的方案，以确保在当前环境下的兼容性
        original_proxies = {
            'HTTP_PROXY': os.environ.pop('HTTP_PROXY', None),
            'HTTPS_PROXY': os.environ.pop('HTTPS_PROXY', None),
            'ALL_PROXY': os.environ.pop('ALL_PROXY', None),
        }

        try:
            # 在没有代理环境变量的上下文中创建客户端
            self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.default_model = self.model
        except Exception as e:
            # 如果发生错误，也要确保环境变量被恢复
            raise ConnectionError(f"Failed to configure OpenAI client: {e}")
        finally:
            # 无论成功与否，都恢复环境变量，避免影响程序的其他部分
            for key, value in original_proxies.items():
                if value is not None:
                    os.environ[key] = value

    def generate(self, prompt: str, **kwargs) -> str:
        """
        Generate text using OpenAI.
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, **kwargs)

    def chat(self, messages: List, **kwargs) -> str:
        """
        Chat with OpenAI.
        """
        model = kwargs.pop('model', self.default_model)
        if model != self.model:
            raise ValueError(f"Model '{model}' is not the configured model for provider '{self.name}'. Configured model: {self.model}")
            
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                timeout=self.timeout,
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            raise
