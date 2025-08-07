from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

class DigitalHumanProvider(ABC):
    @abstractmethod
    def generate_video(self, audio_file_path: str, character_name: str, segments_json: Optional[str] = None) -> Dict[str, Any]:
        pass
