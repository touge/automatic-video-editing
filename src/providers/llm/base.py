from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseLlmProvider(ABC):
    """
    LLM提供者的抽象基类。
    """
    def __init__(self, name: str, config: dict):
        """
        初始化提供者。
        :param name: 提供者的名称 (e.g., 'ollama', 'gemini')
        :param config: 该提供者的特定配置。
        """
        self.name = name
        self.config = config

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        """
        根据给定的提示生成文本。
        """
        pass

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        进行多轮对话。
        """
        pass

    def __repr__(self):
        return f"<{self.__class__.__name__}(name='{self.name}')>"