import ollama
from .base import BaseLlmProvider
from src.logger import log
from typing import List, Dict, Any

class OllamaProvider(BaseLlmProvider):
    """
    Ollama LLM 提供者。
    """
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.model = self.config.get('model')
        if not self.model:
            raise ValueError("Ollama provider config must contain a 'model' key.")
        
        try:
            self.client = ollama.Client(
                host=self.config.get('host'),
                timeout=self.config.get('timeout', 60)
            )
            # 可以添加一个快速的连接检查
            # self.client.list() 
        except Exception as e:
            raise ConnectionError(f"Failed to initialize Ollama client: {e}")

    def generate(self, prompt: str, **kwargs) -> str:
        """
        使用Ollama生成文本。
        """
        try:
            # 将所有额外的关键字参数打包到 'options' 字典中
            options = kwargs if kwargs else {}
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                options=options
            )
            return response.get('response', '')
        except ollama.ResponseError as e:
            log.error(f"Ollama API error (generate): {e.error}")
            if "model" in e.error.lower() and "not found" in e.error.lower():
                log.error(f"Model '{self.model}' not found. Please pull it with `ollama pull {self.model}`.")
            raise
        except Exception as e:
            log.error(f"An unexpected error occurred with Ollama (generate): {e}")
            raise

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        使用Ollama进行聊天。
        """
        try:
            # 将所有额外的关键字参数打包到 'options' 字典中
            options = kwargs if kwargs else {}
            response = self.client.chat(
                model=self.model,
                messages=messages,
                options=options
            )
            return response['message']['content']
        except ollama.ResponseError as e:
            log.error(f"Ollama API error (chat): {e.error}")
            if "model" in e.error.lower() and "not found" in e.error.lower():
                log.error(f"Model '{self.model}' not found. Please pull it with `ollama pull {self.model}`.")
            raise
        except Exception as e:
            log.error(f"An unexpected error occurred with Ollama (chat): {e}")
            raise