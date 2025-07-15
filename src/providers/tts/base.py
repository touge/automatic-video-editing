from abc import ABC, abstractmethod
from typing import Dict

class BaseTtsProvider(ABC):
    """
    TTS提供者的抽象基类。
    """
    def __init__(self, name: str, config: dict):
        """
        初始化提供者。
        :param name: 提供者的名称 (e.g., 'custom_tts')
        :param config: 该提供者的特定配置。
        """
        self.name = name
        self.config = config

    @abstractmethod
    def synthesize(self, text: str, **kwargs) -> Dict:
        """
        根据给定的文本合成语音。
        :param text: 要合成的文本。
        :param kwargs: 特定于提供者的其他参数。
        :return: 包含音频URL或其他相关信息的字典。
        """
        pass

    def __repr__(self):
        return f"<{self.__class__.__name__}(name='{self.name}')>"
