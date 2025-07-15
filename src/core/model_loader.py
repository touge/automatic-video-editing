# -*- coding: utf-8 -*-
import logging
from threading import Lock
from faster_whisper import WhisperModel
from sentence_transformers import SentenceTransformer
from opencc import OpenCC
from src.config_loader import Config
import os

# Conditionally import ONNX-related classes
try:
    from optimum.onnxruntime import ORTModelForFeatureExtraction
    from transformers import AutoTokenizer
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

class SingletonMeta(type):
    _instances = {}
    _lock: Lock = Lock()

    def __call__(cls, *args, **kwargs):
        with cls._lock:
            if cls not in cls._instances:
                instance = super().__call__(*args, **kwargs)
                cls._instances[cls] = instance
        return cls._instances[cls]

class ModelLoader(metaclass=SingletonMeta):
    """
    A singleton class to load and provide access to shared models.
    Ensures that each model is loaded only once.
    """
    def __init__(self, config: Config):
        if not config:
            raise RuntimeError("A valid Config object must be provided to initialize ModelLoader.")
            
        logging.info("Initializing ModelLoader singleton...")
        self.config = config
        self._local_bash_path = self.config.get('paths.local_models.bash_path', 'models')

        # audio_path = os.path.join(audio_segments_dir, f"{i}.wav")
        # os.path.join(self._load_models_base_path, 'whisper')

        self.whisper_model_path = os.path.join(
            self._local_bash_path, 
            self.config.get('paths.local_models.whisper','whisper')
        )
        
        if not self.whisper_model_path:
            raise ValueError("Whisper model path ('paths.local_models.whisper') is not defined in the configuration file.")

        self.whisper_model = None
        self.sentence_model = None
        self.opencc = None
        self._load_models()

    def _load_sentence_transformer(self):
        """Loads the Sentence Transformer model based on the config."""
        use_onnx = self.config.get('paths.local_models.sentence_transformer.use_onnx', False)

        model_path = os.path.join(
            self._local_bash_path,
            self.config.get('paths.local_models.sentence_transformer.path')
        )

        if not model_path:
            raise ValueError("Sentence Transformer path ('paths.local_models.sentence_transformer.path') is not defined in config.")

        if use_onnx:
            if not ONNX_AVAILABLE:
                raise ImportError("ONNX dependencies are not installed. Please run 'pip install optimum[onnxruntime]'")
            logging.info(f"Loading ONNX SentenceTransformer model from: '{model_path}'")
            # For ONNX, we need to load the model and tokenizer separately.
            # The SentenceTransformer class can't directly handle this, so we create a compatible object.
            onnx_model = ORTModelForFeatureExtraction.from_pretrained(model_path)
            tokenizer = AutoTokenizer.from_pretrained(model_path)
            
            # We create a simple wrapper object that mimics SentenceTransformer's `encode` method.
            class OnnxSentenceTransformer:
                def __init__(self, model, tokenizer):
                    self.model = model
                    self.tokenizer = tokenizer

                def encode(self, text, show_progress_bar=False):
                    inputs = self.tokenizer(text, padding=True, truncation=True, return_tensors="pt")
                    outputs = self.model(**inputs)
                    # Mean pooling
                    token_embeddings = outputs.last_hidden_state
                    attention_mask = inputs['attention_mask']
                    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
                    sum_embeddings = (token_embeddings * input_mask_expanded).sum(1)
                    sum_mask = input_mask_expanded.sum(1)
                    return (sum_embeddings / sum_mask).detach().cpu().numpy()

            self.sentence_model = OnnxSentenceTransformer(onnx_model, tokenizer)
        else:
            logging.info(f"Loading standard PyTorch SentenceTransformer model from: '{model_path}'")
            self.sentence_model = SentenceTransformer(model_path)
        
        logging.info("SentenceTransformer model loaded successfully.")

    def _load_models(self):
        """Loads all necessary models from paths specified in the config."""
        try:
            logging.info("Loading OpenCC model (t2s)...")
            self.opencc = OpenCC('t2s')
            logging.info("OpenCC model loaded.")

            self._load_sentence_transformer()

            logging.info(f"Loading Whisper model from local path: '{self.whisper_model_path}'...")
            self.whisper_model = WhisperModel(self.whisper_model_path, device="cuda", compute_type="int8")
            logging.info("Whisper model loaded.")

        except Exception as e:
            logging.error(f"Failed to load one or more models: {e}", exc_info=True)
            # Depending on the application, you might want to raise the exception
            # or handle it gracefully.
            raise

    def get_whisper_model(self):
        if not self.whisper_model:
            raise RuntimeError("Whisper model is not loaded.")
        return self.whisper_model

    def get_sentence_model(self):
        if not self.sentence_model:
            raise RuntimeError("SentenceTransformer model is not loaded.")
        return self.sentence_model

    def get_opencc(self):
        if not self.opencc:
            raise RuntimeError("OpenCC model is not loaded.")
        return self.opencc
