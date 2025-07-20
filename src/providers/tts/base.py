import time
from abc import ABC, abstractmethod
from typing import Dict, Callable, Any
from src.logger import log

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
        self.max_retries = self.config.get('max_retries', 3)
        self.retry_delays = self.config.get('retry_delays', [2, 5, 10]) # 秒

    def _execute_with_retry(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """
        执行一个函数，并在失败时进行重试。
        :param func: 要执行的函数。
        :param args: 传递给函数的 Positional arguments。
        :param kwargs: 传递给函数的 Keyword arguments。
        :return: 函数的返回值。
        :raises Exception: 如果所有重试都失败。
        """
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log.error(f"Provider '{self.name}' operation failed (Attempt {attempt + 1}/{self.max_retries + 1}): {e}")
                if attempt < self.max_retries:
                    delay = self.retry_delays[attempt] if attempt < len(self.retry_delays) else self.retry_delays[-1]
                    log.warning(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    log.error(f"Max retries reached for provider '{self.name}'. Raising exception.")
                    raise # 所有重试都失败，抛出异常

    @abstractmethod
    def synthesize(self, text: str, task_id: str, **kwargs) -> Dict:
        """
        根据给定的文本合成语音。
        :param text: 要合成的文本。
        :param task_id: 当前任务的ID，用于管理文件路径。
        :param kwargs: 特定于提供者的其他参数。
        :return: 包含音频URL或本地路径的字典。
        """
        pass

    def __repr__(self):
        return f"<{self.__class__.__name__}(name='{self.name}')>"
