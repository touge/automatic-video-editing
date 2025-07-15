# -*- coding: utf-8 -*-
import logging
from tqdm import tqdm
from thefuzz import fuzz
from sentence_transformers import util
from .model_loader import ModelLoader
from .text import TextProcessor

class Searcher:
    """
    Handles alignment of text to audio transcriptions and semantic search.
    """
    def __init__(self, model_loader: ModelLoader, text_processor: TextProcessor):
        self.sentence_model = model_loader.get_sentence_model()
        self.text_processor = text_processor

    def _encode_text(self, text: str):
        """Encodes a single text string into an embedding."""
        if not self.sentence_model:
            logging.error("SentenceTransformer model not loaded. Cannot encode text.")
            return None
        return self.sentence_model.encode(text, show_progress_bar=False)

    def linear_align(self, target_lines, whisper_words, debug=False):
        """Aligns target text lines with whisper words using a linear, sliding-window approach."""
        aligned_results = []
        used_word_indices = set()
        whisper_idx = 0

        for line in tqdm(target_lines, desc="Linearly Aligning Text"):
            normalized_line = self.text_processor.normalize(line)
            if not normalized_line:
                continue

            search_start_idx = whisper_idx
            max_search_words = 150
            search_window_size = min(len(normalized_line) * 3 + 20, max_search_words)
            
            best_score = -1
            best_match_info = None
            
            search_end_idx = min(search_start_idx + search_window_size, len(whisper_words))

            if search_start_idx >= len(whisper_words):
                if debug: logging.info(f"DEBUG: No more whisper words to search for line: '{line}'")
                continue

            for i in range(search_start_idx, search_end_idx):
                for j in range(i, search_end_idx):
                    sub_sequence = whisper_words[i:j+1]
                    if not sub_sequence: continue
                    
                    sub_sequence_text = "".join([w['word'] for w in sub_sequence])
                    normalized_sub_sequence = self.text_processor.normalize(sub_sequence_text)
                    
                    current_score = fuzz.token_set_ratio(normalized_line, normalized_sub_sequence)
                    
                    if current_score > best_score:
                        best_score = current_score
                        best_match_info = {
                            "words": sub_sequence,
                            "start_idx": i,
                            "end_idx": j + 1,
                        }
            
            match_threshold = 75

            if best_score >= match_threshold:
                aligned_results.append({
                    "text": line,
                    "start": best_match_info['words'][0]['start'],
                    "end": best_match_info['words'][-1]['end'],
                    "embedding": self._encode_text(line),
                    "source": "text_file"
                })
                whisper_idx = best_match_info['end_idx']
                for k in range(best_match_info['start_idx'], best_match_info['end_idx']):
                    used_word_indices.add(k)
            else:
                whisper_idx += max(1, len(normalized_line) // 5)
                whisper_idx = min(whisper_idx, len(whisper_words))

        return aligned_results, used_word_indices

    def search(self, query_text, aligned_data):
        """Performs a semantic search for a query within the aligned data."""
        query_embedding = self._encode_text(query_text)
        if query_embedding is None:
            logging.error("Could not encode query text.")
            return None

        best_match = None
        max_similarity = -1.0

        for item in aligned_data:
            segment_embedding = item.get('embedding')
            if segment_embedding is None:
                continue
            
            similarity = util.cos_sim(query_embedding, segment_embedding).item()

            if similarity > max_similarity:
                max_similarity = similarity
                best_match = {
                    "text": item.get('text'),
                    "start": item.get('start'),
                    "end": item.get('end'),
                    "similarity": similarity
                }
        
        return best_match
