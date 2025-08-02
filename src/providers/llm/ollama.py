import os
import ollama
from .base import BaseLlmProvider
from src.logger import log
from typing import List, Dict, Any
from contextlib import contextmanager

@contextmanager
def no_proxy():
    """
    一个更强力的上下文管理器，用于临时禁用所有已知的代理环境变量。
    """
    proxy_keys = [
        'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
        'http_proxy', 'https_proxy', 'all_proxy'
    ]
    original_proxies = {key: os.environ.get(key) for key in proxy_keys}
    
    proxies_to_remove = {k: v for k, v in original_proxies.items() if v is not None}

    if proxies_to_remove:
        log.info(f"Temporarily disabling system proxies: {list(proxies_to_remove.keys())}")

    try:
        for key in proxies_to_remove:
            if key in os.environ:
                del os.environ[key]
        yield
    finally:
        for key, value in proxies_to_remove.items():
            os.environ[key] = value
        if proxies_to_remove:
            log.info("System proxy settings restored.")

class OllamaProvider(BaseLlmProvider):
    """
    Ollama LLM 提供者。
    """
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.model = self.config.get('model')
        if not self.model:
            raise ValueError("Ollama provider config must contain a 'model' field.")
        
        try:
            # 在初始化客户端时临时禁用代理，以确保它不会继承系统范围的代理设置
            with no_proxy():
                self.client = ollama.Client(
                    host=self.config.get('host'),
                    timeout=self.config.get('timeout', 600)
                )
            self.default_model = self.model
        except Exception as e:
            # 捕获并重新引发更具体的异常
            raise ConnectionError(f"Failed to initialize Ollama client: {e}")

    def generate(self, prompt: str, **kwargs) -> str:
        """
        使用Ollama生成文本。
        """
        model = kwargs.pop('model', self.default_model)
        if model != self.model:
            raise ValueError(f"Model '{model}' is not the configured model for provider '{self.name}'. Configured model: {self.model}")

        try:
            options = kwargs if kwargs else {}
            response = self.client.generate(
                model=model,
                prompt=prompt,
                options=options
            )
            return response.get('response', '')
        except ollama.ResponseError as e:
            if "model" in e.error.lower() and "not found" in e.error.lower():
                log.error(f"Model '{model}' not found. Please pull it with `ollama pull {model}`.")
            raise
        except Exception as e:
            raise

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        使用Ollama进行聊天。
        """
        model = kwargs.pop('model', self.default_model)
        if model != self.model:
            raise ValueError(f"Model '{model}' is not the configured model for provider '{self.name}'. Configured model: {self.model}")

        try:
            options = kwargs if kwargs else {}
            response = self.client.chat(
                model=model,
                messages=messages,
                options=options
            )
            return response['message']['content']
        except ollama.ResponseError as e:
            if "model" in e.error.lower() and "not found" in e.error.lower():
                log.error(f"Model '{model}' not found. Please pull it with `ollama pull {model}`.")
            raise
        except Exception as e:
            raise
