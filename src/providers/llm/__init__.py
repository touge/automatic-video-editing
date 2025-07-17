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
    # 'gemini': GeminiProvider,
    'siliconflow': SiliconflowProvider,
    'openai': OpenAIProvider,
}

class LlmManager:
    """
    管理所有已配置的LLM提供者。
    这是一个单例模式的实现，以确保在整个应用程序中只有一个实例。
    """
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
            self.providers: Dict[str, BaseLlmProvider] = {}
            self.default_provider_name: Optional[str] = None
            self.ordered_providers: List[str] = []
            self._initialized = True
            log.warning("LlmManager initialized without configuration.")
            return

        self.providers: Dict[str, BaseLlmProvider] = {}
        llm_config = config.get('llm_providers', {})
        self.default_provider_name = llm_config.get('default')
        
        enabled_providers = []
        for name, provider_config in llm_config.items():
            if name == 'default':
                continue
            if provider_config.get('enabled'):
                if name in _PROVIDER_CLASSES:
                    try:
                        provider_class = _PROVIDER_CLASSES[name]
                        self.providers[name] = provider_class(name, provider_config)
                        enabled_providers.append(name)
                        log.info(f"Successfully loaded LLM provider: '{name}'")
                    except Exception as e:
                        log.error(f"Failed to load LLM provider '{name}': {e}")
                else:
                    log.warning(f"Unknown LLM provider type configured: '{name}'")
        
        # 设置有序的提供者列表以进行故障切换
        self.ordered_providers = []
        if self.default_provider_name and self.default_provider_name in self.providers:
            self.ordered_providers.append(self.default_provider_name)
        
        for provider in enabled_providers:
            if provider != self.default_provider_name:
                self.ordered_providers.append(provider)

        if not self.ordered_providers:
            log.error("No LLM providers are enabled or available. The application may not function correctly.")
            self.default_provider_name = None
        elif self.default_provider_name not in self.providers:
            log.warning(f"Default LLM provider '{self.default_provider_name}' is not available or enabled.")
            self.default_provider_name = self.ordered_providers[0]
            log.info(f"Falling back to use '{self.default_provider_name}' as default LLM provider.")

        self._initialized = True

    def get_provider(self, name: Optional[str] = None) -> Optional[BaseLlmProvider]:
        """
        获取一个LLM提供者实例。
        如果不提供名称，则返回默认提供者。
        """
        if name:
            return self.providers.get(name)
        
        if self.default_provider_name:
            return self.providers.get(self.default_provider_name)
            
        return None

    def _execute_with_failover(self, method_name: str, *args, **kwargs) -> Any:
        """
        使用故障切换逻辑执行提供者的方法（'generate' 或 'chat'）。
        """
        if not self.ordered_providers:
            log.error("No LLM providers available to execute the request.")
            sys.exit(1)

        last_exception = None
        # 提取 model 参数，以便可以将其传递给每个提供者
        model_override = kwargs.get('model')

        # 遍历有序提供者列表的副本，以便在失败时可以安全地从中移除项目
        for provider_name in list(self.ordered_providers):
            provider = self.providers.get(provider_name)
            if not provider:
                continue

            # 如果指定了模型，请检查该提供者是否支持它
            if model_override and model_override not in provider.models:
                log.warning(f"Provider '{provider_name}' does not support the specified model '{model_override}'. Skipping.")
                continue

            try:
                log.info(f"Attempting to use LLM provider: '{provider_name}'")
                method: Callable = getattr(provider, method_name)
                return method(*args, **kwargs)
            except Exception as e:
                last_exception = e
                log.warning(f"LLM provider '{provider_name}' failed. Removing it from the available list for this task.")
                # 从原始列表中移除失败的提供者，以避免在此任务中再次调用它
                self.ordered_providers.remove(provider_name)
        
        log.error(f"All available LLM providers failed. Last error: {last_exception}")
        sys.exit(1)

    def generate_with_failover(self, prompt: str, **kwargs) -> str:
        """
        使用故障切换逻辑生成文本。
        """
        return self._execute_with_failover('generate', prompt, **kwargs)

    def chat_with_failover(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        使用故障切换逻辑进行聊天。
        """
        return self._execute_with_failover('chat', messages, **kwargs)

    @property
    def default(self) -> Optional[BaseLlmProvider]:
        """
        获取默认的LLM提供者实例的属性。
        """
        return self.get_provider()

# 全局实例
# 在应用启动时，需要使用主配置来初始化它
