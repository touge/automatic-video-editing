import google.generativeai as genai
from .base import BaseLlmProvider
from src.logger import log
from typing import List, Dict, Any

class GeminiProvider(BaseLlmProvider):
    """
    Google Gemini LLM 提供者。
    """
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.api_key = self.config.get('api_key')
        if not self.api_key:
            raise ValueError("Gemini provider config must contain an 'api_key'.")
        
        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(self.config.get('model', 'gemini-1.5-pro-latest'))
        except Exception as e:
            raise ConnectionError(f"Failed to configure Gemini client: {e}")

    def generate(self, prompt: str, **kwargs) -> str:
        """
        使用Gemini生成文本。
        """
        try:
            response = self.model.generate_content(prompt, **kwargs)
            return response.text
        except Exception as e:
            log.error(f"An unexpected error occurred with Gemini (generate): {e}")
            raise

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        使用Gemini进行聊天。
        Gemini API的'chat'通常是通过历史消息记录来管理的。
        这里我们简化处理，直接将多轮消息拼接成一个prompt。
        更复杂的场景可能需要一个chat session对象。
        """
        try:
            # Gemini 的 chat 输入是 content 列表
            history = []
            for msg in messages:
                role = 'user' if msg['role'] == 'user' else 'model'
                history.append({'role': role, 'parts': [msg['content']]})
            
            # 最后一个不能是 model
            if history and history[-1]['role'] == 'model':
                history.pop()

            chat_session = self.model.start_chat(history=history)
            response = chat_session.send_message(messages[-1]['content'], **kwargs)
            return response.text
        except Exception as e:
            log.error(f"An unexpected error occurred with Gemini (chat): {e}")
            raise