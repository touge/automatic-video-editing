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
        self.models = self.config.get('models', [])
        
        if not self.api_key:
            raise ValueError("Gemini provider config must contain an 'api_key'.")
        if not self.models:
            raise ValueError("Gemini provider config must contain a 'models' list.")
            
        try:
            genai.configure(api_key=self.api_key)
            self.default_model = self.models[0]
        except Exception as e:
            raise ConnectionError(f"Failed to configure Gemini client: {e}")

    def _get_model(self, model_name: str):
        return genai.GenerativeModel(model_name)

    def generate(self, prompt: str, **kwargs) -> str:
        """
        使用Gemini生成文本。
        """
        model_name = kwargs.pop('model', self.default_model)
        if model_name not in self.models:
            raise ValueError(f"Model '{model_name}' is not available for provider '{self.name}'. Available models: {self.models}")
        
        model = self._get_model(model_name)
        try:
            response = model.generate_content(prompt, **kwargs)
            return response.text
        except Exception as e:
            raise

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        使用Gemini进行聊天。
        """
        model_name = kwargs.pop('model', self.default_model)
        if model_name not in self.models:
            raise ValueError(f"Model '{model_name}' is not available for provider '{self.name}'. Available models: {self.models}")

        model = self._get_model(model_name)
        try:
            history = []
            for msg in messages:
                role = 'user' if msg['role'] == 'user' else 'model'
                history.append({'role': role, 'parts': [msg['content']]})
            
            if history and history[-1]['role'] == 'model':
                history.pop()

            chat_session = model.start_chat(history=history)
            response = chat_session.send_message(messages[-1]['content'], **kwargs)
            return response.text
        except Exception as e:
            raise
