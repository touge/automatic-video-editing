# -*- coding: utf-8 -*-
import logging
from tqdm import tqdm
from .model_loader import ModelLoader

class AudioProcessor:
    """
    Handles audio processing tasks, primarily transcription.
    """
    def __init__(self, model_loader: ModelLoader):
        self.whisper_model = model_loader.get_whisper_model()

    def transcribe(self, audio_file: str):
        """
        Transcribes an audio file using the pre-loaded faster-whisper model,
        and extracts word-level timestamps.

        Args:
            audio_file (str): Path to the audio file.

        Returns:
            A tuple containing:
            - full_text (str): The complete transcribed text.
            - segments_info (list): A list of segments with word-level details.
            - info (object): Information about the transcription process.
        """
        if not self.whisper_model:
            logging.error("Whisper model not available for transcription.")
            return None, None, None

        logging.info(f"Transcribing audio file: {audio_file} (this may take a while)...")
        
        segments, info = self.whisper_model.transcribe(
            audio_file, 
            beam_size=5, 
            word_timestamps=True
        )
        
        full_text = ""
        segments_info = []
        
        # Use tqdm for progress indication
        for segment in tqdm(segments, desc="Processing transcription segments"):
            full_text += segment.text
            words_info = []
            if segment.words:
                for word in segment.words:
                    words_info.append({
                        "word": word.word,
                        "start": word.start,
                        "end": word.end
                    })
            
            segments_info.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "words": words_info
            })
            
        logging.info("Audio transcription complete.")
        return full_text, segments_info, info
