import requests
from .base import BaseTtsProvider
from src.logger import log
from typing import Dict

class CosyVoiceTtsProvider(BaseTtsProvider):
    """
    A TTS provider for CosyVoice that works via an HTTP POST request.
    """
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.base_endpoint = self.config.get('base_endpoint', '').rstrip('/')
        self.api_key = self.config.get('api_key')
        self.default_speaker = self.config.get('default_speaker')
        self.api_path = "/speak_as"  # Hardcoded API path for this provider
        
        if not self.base_endpoint:
            raise ValueError("CosyVoice TTS provider config must contain a 'base_endpoint'.")
        if not self.default_speaker:
            raise ValueError("CosyVoice TTS provider config must contain a 'default_speaker'.")

    def synthesize(self, text: str, **kwargs) -> Dict:
        """
        Synthesize speech using the CosyVoice TTS service.
        """
        silent = kwargs.get('silent', False)
        full_api_url = self.base_endpoint + self.api_path
        
        headers = {
            'accept': 'application/json',
            'Content-Type': 'application/json'
        }
        if self.api_key:
            headers['x-api-key'] = self.api_key

        speaker = kwargs.get('speaker', self.default_speaker)
        return_type = kwargs.get('return_type', 'url')
        speed = kwargs.get('speed', 0.95)

        payload = {
            "speaker": speaker,
            "text": text,
            "return_type": return_type,
            "speed": speed
        }

        try:
            if not silent:
                log.info(f"Sending TTS request to {full_api_url} with speaker '{speaker}'")
            response = requests.post(full_api_url, headers=headers, json=payload)
            response.raise_for_status()
            
            data = response.json()
            if data.get('status') == 'ok':
                # Assemble the full URL if the response is a relative path
                audio_url = data.get('url', '')
                if not audio_url.startswith(('http://', 'https://')):
                    audio_url = self.base_endpoint + audio_url
                data['url'] = audio_url
                if not silent:
                    log.info(f"TTS synthesis successful. Full audio URL: {audio_url}")
                return data
            else:
                if not silent:
                    log.error(f"TTS synthesis failed with status: {data.get('status')}. Reason: {data.get('message')}")
                raise Exception(f"TTS API returned an error: {data.get('message')}")

        except requests.exceptions.RequestException as e:
            if not silent:
                log.error(f"Failed to connect to TTS service at {full_api_url}: {e}")
            raise
        except Exception as e:
            if not silent:
                log.error(f"An unexpected error occurred during TTS synthesis: {e}")
            raise
