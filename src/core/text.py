# -*- coding: utf-8 -*-
import logging
import warnings
import re
import cn2an
from .model_loader import ModelLoader

class TextProcessor:
    """
    Handles text processing tasks like normalization and time formatting.
    """
    def __init__(self, model_loader: ModelLoader):
        self.cc = model_loader.get_opencc()

    def normalize(self, text: str) -> str:
        """
        Performs deep normalization on text for robust comparison.
        - Converts Traditional to Simplified Chinese.
        - Converts Chinese numerals to Arabic numerals.
        - Removes punctuation and converts to lowercase.
        """
        if not self.cc:
            logging.error("OpenCC model not loaded. Cannot normalize text.")
            return text

        simplified_text = self.cc.convert(text)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            try:
                # Transform Chinese numerals to Arabic numerals
                normalized_text = cn2an.transform(simplified_text, "cn2an")
            except (ValueError, KeyError):
                # Fallback if cn2an fails (e.g., on non-numeric text)
                normalized_text = simplified_text
        
        # Remove all non-alphanumeric characters (keeps Chinese chars and letters)
        # and convert to lowercase
        return re.sub(r'[^\w]', '', normalized_text).lower()

    @staticmethod
    def format_time(seconds: float) -> str:
        """
        Converts seconds to SRT timecode format (HH:MM:SS,ms).
        """
        assert seconds >= 0, "Cannot format negative seconds"
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s - int(s)) * 1000):03d}"
