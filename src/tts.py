from src.config_loader import config
from src.providers.tts import TtsManager
from typing import Dict

class TTS:
    """
    A high-level class for Text-to-Speech synthesis.
    """
    def __init__(self):
        self.manager = TtsManager(config.data)

    def synthesize(self, text: str, task_id: str, **kwargs) -> Dict:
        """
        Synthesize speech using the configured TTS providers with failover.

        :param text: The text to synthesize.
        :param task_id: The ID of the current task.
        :param kwargs: Additional parameters to pass to the provider, 
                       e.g., speaker="speaker_name".
        :return: A dictionary containing the result from the TTS provider.
        """
        # Pass task_id as a keyword argument to be included in **kwargs
        return self.manager.synthesize(text, task_id=task_id, **kwargs)

# 全局单例实例，初始为 None
_tts_instance = None

def get_tts_instance():
    """
    获取 TTS 类的单例。

    这种懒加载模式确保 TtsManager 仅在首次需要时才被实例化，
    避免了在应用启动时就进行不必要的服务检查和资源加载。
    """
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = TTS()
    return _tts_instance

if __name__ == '__main__':
    # Example usage:
    # 注意：现在我们通过 get_tts_instance() 来获取实例
    tts_service = get_tts_instance()
    text_to_speak = "你好，这是一个测试。"
    
    # Synthesize with default speaker
    result = tts_service.synthesize(text_to_speak, task_id="test_task")
    print("Synthesis result (default speaker):", result)

    # Synthesize with a specific speaker
    result_custom = tts_service.synthesize(text_to_speak, task_id="test_task", speaker="另一个声音")
    print("Synthesis result (custom speaker):", result_custom)
