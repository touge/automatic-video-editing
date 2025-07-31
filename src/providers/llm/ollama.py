import os
import ollama
from .base import BaseLlmProvider
from src.logger import log
from typing import List, Dict, Any
from contextlib import contextmanager

@contextmanager
def no_proxy():
    """A context manager to temporarily disable proxy settings."""
    original_proxies = {
        'http': os.environ.get('HTTP_PROXY'),
        'https': os.environ.get('HTTPS_PROXY')
    }
    try:
        if 'HTTP_PROXY' in os.environ:
            del os.environ['HTTP_PROXY']
        if 'HTTPS_PROXY' in os.environ:
            del os.environ['HTTPS_PROXY']
        yield
    finally:
        if original_proxies['http']:
            os.environ['HTTP_PROXY'] = original_proxies['http']
        if original_proxies['https']:
            os.environ['HTTPS_PROXY'] = original_proxies['https']

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
            # Initialization should be lightweight, no proxy manipulation here
            self.client = ollama.Client(
                host=self.config.get('host'),
                timeout=self.config.get('timeout', 60)
            )
            self.default_model = self.model
        except Exception as e:
            raise ConnectionError(f"Failed to initialize Ollama client: {e}")

    def generate(self, prompt: str, **kwargs) -> str:
        """
        使用Ollama生成文本。
        """
        model = kwargs.pop('model', self.default_model)
        if model != self.model:
            raise ValueError(f"Model '{model}' is not the configured model for provider '{self.name}'. Configured model: {self.model}")

        try:
            log.info("Disabling proxy for Ollama generate call.")
            with no_proxy():
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
            log.info("Disabling proxy for Ollama chat call.")
            with no_proxy():
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
