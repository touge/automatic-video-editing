import openai
from .base import BaseLlmProvider
from typing import List, Dict

class OpenAIProvider(BaseLlmProvider):
    """
    OpenAI LLM Provider.
    """
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.api_key = self.config.get('api_key')
        self.base_url = self.config.get('base_url')
        self.model = self.config.get('model') # Expect a single model string
        
        if not self.api_key:
            raise ValueError("OpenAI provider config must contain an 'api_key'.")
        if not self.model: # Check for single model field
            raise ValueError("OpenAI provider config must contain a 'model' field.")
        
        try:
            self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.default_model = self.model # The single model is the default
        except Exception as e:
            raise ConnectionError(f"Failed to configure OpenAI client: {e}")

    def generate(self, prompt: str, **kwargs) -> str:
        """
        Generate text using OpenAI.
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, **kwargs)

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Chat with OpenAI.
        """
        model = kwargs.pop('model', self.default_model)
        if model != self.model: # Check if the requested model matches the configured single model
            raise ValueError(f"Model '{model}' is not the configured model for provider '{self.name}'. Configured model: {self.model}")
            
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as e:
            raise
