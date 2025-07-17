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

# Create a global instance for easy access
tts = TTS()

if __name__ == '__main__':
    # Example usage:
    text_to_speak = "你好，这是一个测试。"
    
    # Synthesize with default speaker
    result = tts.synthesize(text_to_speak)
    print("Synthesis result (default speaker):", result)

    # Synthesize with a specific speaker
    result_custom = tts.synthesize(text_to_speak, speaker="另一个声音")
    print("Synthesis result (custom speaker):", result_custom)
