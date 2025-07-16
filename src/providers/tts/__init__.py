import sys
from .base import BaseTtsProvider
from .cosyvoice import CosyVoiceTtsProvider
from .siliconflow import SiliconflowTtsProvider
from src.logger import log
from typing import Dict, Optional, List, Any, Callable

# Map provider names to their classes
_PROVIDER_CLASSES = {
    'cosyvoice': CosyVoiceTtsProvider,
    'siliconflow': SiliconflowTtsProvider,
}

class TtsManager:
    """
    Manages all configured TTS providers.
    This is a singleton to ensure a single instance throughout the application.
    """
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TtsManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[Dict] = None):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        if config is None:
            self.providers: Dict[str, BaseTtsProvider] = {}
            self.default_provider_name: Optional[str] = None
            self.ordered_providers: List[str] = []
            self._initialized = True
            log.warning("TtsManager initialized without configuration.")
            return

        self.providers: Dict[str, BaseTtsProvider] = {}
        tts_config = config.get('tts_providers', {})
        self.default_provider_name = tts_config.get('default')
        
        enabled_providers = []
        for name, provider_config in tts_config.items():
            if name == 'default':
                continue
            if provider_config.get('enabled'):
                if name in _PROVIDER_CLASSES:
                    try:
                        provider_class = _PROVIDER_CLASSES[name]
                        self.providers[name] = provider_class(name, provider_config)
                        enabled_providers.append(name)
                        # log.info(f"Successfully loaded TTS provider: '{name}'")
                    except Exception as e:
                        log.error(f"Failed to load TTS provider '{name}': {e}")
                else:
                    log.warning(f"Unknown TTS provider type configured: '{name}'")
        
        self.ordered_providers = []
        if self.default_provider_name and self.default_provider_name in self.providers:
            self.ordered_providers.append(self.default_provider_name)
        
        for provider in enabled_providers:
            if provider != self.default_provider_name:
                self.ordered_providers.append(provider)

        if not self.ordered_providers:
            log.error("No TTS providers are enabled or available.")
            self.default_provider_name = None
        elif self.default_provider_name not in self.providers:
            log.warning(f"Default TTS provider '{self.default_provider_name}' is not available or enabled.")
            self.default_provider_name = self.ordered_providers[0]
            log.info(f"Falling back to use '{self.default_provider_name}' as default TTS provider.")

        self._initialized = True

    def get_provider(self, name: Optional[str] = None) -> Optional[BaseTtsProvider]:
        if name:
            return self.providers.get(name)
        if self.default_provider_name:
            return self.providers.get(self.default_provider_name)
        return None

    def _execute_with_failover(self, method_name: str, *args, **kwargs) -> Any:
        if not self.ordered_providers:
            log.error("No TTS providers available to execute the request.")
            sys.exit(1)

        last_exception = None
        for provider_name in list(self.ordered_providers):
            provider = self.providers.get(provider_name)
            if not provider:
                continue

            try:
                log.info(f"Attempting to use TTS provider: '{provider_name}'")
                method: Callable = getattr(provider, method_name)
                return method(*args, **kwargs)
            except Exception as e:
                last_exception = e
                log.warning(f"TTS provider '{provider_name}' failed. Removing it from the available list for this task.")
                self.ordered_providers.remove(provider_name)
        
        log.error(f"All available TTS providers failed. Last error: {last_exception}")
        sys.exit(1)

    def check_availability(self, task_id: str) -> bool:
        if not self.ordered_providers:
            return False

        for provider_name in list(self.ordered_providers):
            provider = self.providers.get(provider_name)
            if not provider:
                continue
            try:
                # Silently try to synthesize, providing a task_id
                test_result = provider.synthesize("test", task_id=task_id, silent=True)
                # Check for either a URL or a local path
                if test_result and (test_result.get("url") or test_result.get("path")):
                    return True
            except Exception:
                # Ignore exceptions during check, just try the next provider
                continue
        
        # If loop completes, no provider was successful
        return False

    def synthesize_with_failover(self, text: str, **kwargs) -> Dict:
        return self._execute_with_failover('synthesize', text, **kwargs)

    @property
    def default(self) -> Optional[BaseTtsProvider]:
        return self.get_provider()
