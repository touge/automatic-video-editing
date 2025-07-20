import sys
from .base import BaseLlmProvider
from .ollama import OllamaProvider
from .siliconflow import SiliconflowProvider
from .openai import OpenAIProvider
from src.logger import log
from typing import Dict, Optional, List, Any, Callable

# 映射提供者名称到其类
_PROVIDER_CLASSES = {
    'ollama': OllamaProvider,
    'siliconflow': SiliconflowProvider,
    'openai': OpenAIProvider,
}

class LlmManager:
    """
    管理所有已配置的LLM提供者。
    这是一个单例模式的实现，以确保在整个应用程序中只有一个实例。
    """
    _instance = None
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(LlmManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[Dict] = None):
        # 防止重复初始化
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        if config is None:
            self.provider: Optional[BaseLlmProvider] = None
            self.model_name: Optional[str] = None
            self.retries: int = 0
            self._initialized = True
            log.warning("LlmManager initialized without configuration.")
            return

        llm_config = config.get('llm_providers', {})
        used_provider_name = llm_config.get('use')
        self.retries = llm_config.get('retries', 0) # Default to 0 retries if not specified

        if not used_provider_name:
            log.error("No LLM provider specified in 'llm_providers.use' in config.yaml. The application may not function correctly.")
            self.provider = None
            self.model_name = None
            self._initialized = True
            return

        provider_config = llm_config.get(used_provider_name)
        if not provider_config:
            log.error(f"Configuration for LLM provider '{used_provider_name}' not found in config.yaml.")
            self.provider = None
            self.model_name = None
            self._initialized = True
            return

        if used_provider_name not in _PROVIDER_CLASSES:
            log.warning(f"Unknown LLM provider type configured: '{used_provider_name}'.")
            self.provider = None
            self.model_name = None
            self._initialized = True
            return

        try:
            provider_class = _PROVIDER_CLASSES[used_provider_name]
            self.provider = provider_class(used_provider_name, provider_config)
            self.model_name = provider_config.get('model') # Get the single model name
            
            if not self.model_name:
                log.error(f"No model specified for LLM provider '{used_provider_name}' in config.yaml.")
                self.provider = None
                self.model_name = None
                self._initialized = True
                return

            log.info(f"Successfully loaded LLM provider: '{used_provider_name}' with model '{self.model_name}'")
        except Exception as e:
            log.error(f"Failed to load LLM provider '{used_provider_name}': {e}")
            self.provider = None
            self.model_name = None
        
        self._initialized = True

    def get_provider(self) -> Optional[BaseLlmProvider]:
        """
        获取已配置的LLM提供者实例。
        """
        return self.provider

    def _execute_with_retry(self, method_name: str, *args, **kwargs) -> Any:
        """
        使用重试逻辑执行提供者的方法（'generate' 或 'chat'）。
        """
        if not self.provider:
            log.error("No LLM provider is configured or available to execute the request.")
            raise RuntimeError("No LLM provider is configured or available to execute the request.")

        last_exception = None
        # Ensure the model is passed if not already in kwargs
        if 'model' not in kwargs and self.model_name:
            kwargs['model'] = self.model_name

        for attempt in range(self.retries + 1):
            try:
                # 将此日志级别从 INFO 降低到 DEBUG，以减少正常运行时的干扰
                log.debug(f"Attempting to use LLM provider: '{self.provider.name}' (Attempt {attempt + 1}/{self.retries + 1})")
                method: Callable = getattr(self.provider, method_name)
                return method(*args, **kwargs)
            except Exception as e:
                last_exception = e
                log.warning(f"LLM provider '{self.provider.name}' failed on attempt {attempt + 1}: {e}")
                if attempt < self.retries:
                    log.debug(f"Retrying in 1 second...") # 降低重试日志级别
                    time.sleep(1) # Simple delay before retrying
        
        log.error(f"LLM provider '{self.provider.name}' failed after {self.retries + 1} attempts. Last error: {last_exception}")
        raise RuntimeError(f"LLM provider '{self.provider.name}' failed after {self.retries + 1} attempts. Last error: {last_exception}")

    def generate_with_failover(self, prompt: str, **kwargs) -> str:
        """
        使用重试逻辑生成文本。
        """
        return self._execute_with_retry('generate', prompt, **kwargs)

    def chat_with_failover(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        使用重试逻辑进行聊天。
        """
        return self._execute_with_retry('chat', messages, **kwargs)

    @property
    def default(self) -> Optional[BaseLlmProvider]:
        """
        获取已配置的LLM提供者实例的属性。
        """
        return self.get_provider()

# 全局实例
# 在应用启动时，需要使用主配置来初始化它
