from .base import BaseLlmProvider
from .ollama import OllamaProvider
from .gemini import GeminiProvider
from src.logger import log
from typing import Dict, Optional

# 映射提供者名称到其类
_PROVIDER_CLASSES = {
    'ollama': OllamaProvider,
    'gemini': GeminiProvider,
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
            # 在没有提供配置的情况下，可以决定是抛出错误还是创建一个空的管理器
            self.providers: Dict[str, BaseLlmProvider] = {}
            self.default_provider_name: Optional[str] = None
            self._initialized = True
            log.warning("LlmManager initialized without configuration.")
            return

        self.providers: Dict[str, BaseLlmProvider] = {}
        llm_config = config.get('llm_providers', {})
        self.default_provider_name = llm_config.get('default')

        for name, provider_config in llm_config.items():
            if name == 'default':
                continue

            if provider_config.get('enabled'):
                if name in _PROVIDER_CLASSES:
                    try:
                        provider_class = _PROVIDER_CLASSES[name]
                        self.providers[name] = provider_class(name, provider_config)
                        log.info(f"Successfully loaded LLM provider: '{name}'")
                    except Exception as e:
                        log.error(f"Failed to load LLM provider '{name}': {e}")
                else:
                    log.warning(f"Unknown LLM provider type configured: '{name}'")
        
        if self.default_provider_name and self.default_provider_name not in self.providers:
            log.warning(f"Default LLM provider '{self.default_provider_name}' is not available or enabled.")
            # 如果默认的不可用，可以考虑选择一个可用的作为后备
            if self.providers:
                self.default_provider_name = list(self.providers.keys())[0]
                log.info(f"Falling back to use '{self.default_provider_name}' as default LLM provider.")
            else:
                self.default_provider_name = None
        
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

    @property
    def default(self) -> Optional[BaseLlmProvider]:
        """
        获取默认的LLM提供者实例的属性。
        """
        return self.get_provider()

# 全局实例
# 在应用启动时，需要使用主配置来初始化它
# from src.utils import load_config
# config = load_config()
# llm_manager = LlmManager(config)