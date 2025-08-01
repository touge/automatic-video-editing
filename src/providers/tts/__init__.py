import sys
from .base import BaseTtsProvider
from .cosyvoice import CosyVoiceTtsProvider
from .siliconflow import SiliconflowTtsProvider
from .indextts import IndexTtsProvider
from src.logger import log
from typing import Dict, Optional, List, Any, Callable

# Map provider names to their classes
_PROVIDER_CLASSES = {
    'CosyVoice2': CosyVoiceTtsProvider,
    'siliconflow': SiliconflowTtsProvider,
    'IndexTTS': IndexTtsProvider,
}

class TtsManager:
    """
    Manages the configured TTS provider.
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
        
        self.provider: Optional[BaseTtsProvider] = None
        if config is None:
            self._initialized = True
            log.warning("TtsManager initialized without configuration.")
            return

        tts_config = config.get('tts_providers', {})
        provider_name = tts_config.get('use')
        
        if not provider_name:
            log.error("No TTS provider specified in config 'tts_providers.use'.")
            self._initialized = True
            return

        if provider_name in _PROVIDER_CLASSES:
            provider_config = tts_config.get(provider_name)
            if not provider_config:
                log.error(f"Configuration for TTS provider '{provider_name}' is missing.")
                self._initialized = True
                return
            
            try:
                provider_class = _PROVIDER_CLASSES[provider_name]
                self.provider = provider_class(provider_name, provider_config)
                log.info(f"Successfully loaded TTS provider: '{provider_name}'")
            except Exception as e:
                log.error(f"Failed to load TTS provider '{provider_name}': {e}")
                # As per requirement, exit if the chosen provider fails to load
                sys.exit(1)
        else:
            log.error(f"Unknown TTS provider type configured: '{provider_name}'")
            sys.exit(1)

        self._initialized = True

    def get_provider(self) -> Optional[BaseTtsProvider]:
        return self.provider

    def check_availability(self) -> bool:
        """
        Checks if the configured TTS provider is available by performing a test synthesis
        that does not interact with the file system.
        """
        if not self.provider:
            return False
        
        try:
            log.info(f"Performing availability check for TTS provider '{self.provider.name}'...")
            # Perform a test synthesis. task_id is None as no files will be written.
            self.provider.synthesize("test", task_id=None, is_test=True)
            log.success(f"TTS provider '{self.provider.name}' is available.")
            return True
        except Exception as e:
            log.error(f"TTS availability check failed for provider '{self.provider.name}'.")
            # Log the actual error for debugging, but maybe not in full detail to the user.
            log.debug(f"Underlying error: {e}")
            return False

    def synthesize(self, text: str, **kwargs) -> Dict:
        if not self.provider:
            log.error("No TTS provider available to execute the request.")
            sys.exit(1)

        try:
            log.info(f"Attempting to use TTS provider: '{self.provider.name}'")
            return self.provider.synthesize(text, **kwargs)
        except Exception as e:
            log.error(f"TTS provider '{self.provider.name}' failed: {e}")
            # As per requirement, exit if the synthesis fails
            sys.exit(1)

    @property
    def default(self) -> Optional[BaseTtsProvider]:
        return self.get_provider()
