import os
import shutil
import re
import json
import pickle
import requests
from pydub import AudioSegment
from tqdm import tqdm
from typing import List, Dict

import bootstrap
from src.utils import ensure_task_path
from src.logger import log
from src.tts import tts
from src.config_loader import config
from src.core.model_loader import ModelLoader
from src.core.audio import AudioProcessor
from src.core.text import TextProcessor
from src.core.search import Searcher

class AudioPreprocessor:
    def __init__(self, task_id: str, doc_file: str):
        if not task_id or not doc_file:
            raise ValueError("task_id and doc_file must be provided.")
        if not os.path.exists(doc_file):
            raise FileNotFoundError(f"Document file not found at '{doc_file}'")

        self.task_id = task_id
        self.doc_file = doc_file
        
        # Setup paths
        self.task_dir = ensure_task_path(self.task_id)
        self.doc_cache_dir = os.path.join(self.task_dir, ".documents")
        self.audio_cache_dir = os.path.join(self.task_dir, ".audios")
        self.whisper_cache_dir = os.path.join(self.task_dir, ".whisper")
        # self.alignment_cache_dir = os.path.join(self.task_dir, ".alignment")
        self.doc_segments_dir = os.path.join(self.doc_cache_dir, "segments")
        self.audio_segments_dir = os.path.join(self.audio_cache_dir, "segments")
        
        for d in [self.doc_cache_dir, self.audio_cache_dir, self.whisper_cache_dir, self.doc_segments_dir, self.audio_segments_dir]:
            os.makedirs(d, exist_ok=True)

    def run(self):
        log.info(f"--- Starting Audio Preprocessing for Task ID: {self.task_id} ---")
        
        # --- Step 1: TTS and Audio Combination ---
        segments = self._process_document_for_tts()
        if not segments: return

        self._synthesize_audio_segments(segments)
        
        final_audio_path = os.path.join(self.task_dir, "final_audio.wav")
        if os.path.exists(final_audio_path):
            log.info(f"Final audio already exists, skipping combination: {final_audio_path}")
        else:
            if not self._combine_audio_segments(len(segments), final_audio_path):
                return

        # --- Step 2: Subtitle Generation ---
        self._generate_subtitles(final_audio_path)

    def _download_file(self, url: str, destination: str) -> bool:
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with open(destination, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except requests.exceptions.RequestException as e:
            log.error(f"Error downloading {url}: {e}")
            return False

    def _process_document_for_tts(self) -> List[str]:
        log.info("--- Step 2.1: Processing document for TTS ---")
        shutil.copy(self.doc_file, os.path.join(self.doc_cache_dir, "original.txt"))
        log.success("Cached original document.")
        with open(self.doc_file, 'r', encoding='utf-8') as f:
            content = f.read()
        segments = [seg.strip() for seg in content.split('\n\n') if seg.strip()]
        if not segments:
            log.error("No text segments found for TTS.")
            return []
        log.success(f"Document split into {len(segments)} segments for TTS.")
        for i, segment_text in enumerate(segments):
            with open(os.path.join(self.doc_segments_dir, f"{i}.txt"), 'w', encoding='utf-8') as f:
                f.write(segment_text)
        log.success("All TTS text segments cached.")
        return segments

    def _synthesize_audio_segments(self, segments: List[str]):
        log.info("--- Step 2.2: Synthesizing audio for each segment ---")
        for i, segment_text in enumerate(tqdm(segments, desc="Synthesizing Audio")):
            audio_path = os.path.join(self.audio_segments_dir, f"{i}.wav")
            if os.path.exists(audio_path):
                continue
            try:
                response = tts.synthesize(segment_text)
                audio_url = response.get("url")
                if not audio_url or not self._download_file(audio_url, audio_path):
                    log.error(f"Failed to process audio for segment {i}.")
            except Exception as e:
                log.error(f"An error occurred during synthesis for segment {i}: {e}")
        log.success("Finished synthesizing all segments.")

    def _combine_audio_segments(self, num_segments: int, output_path: str) -> bool:
        log.info("\n--- Step 2.3: Combining all audio segments ---")
        valid_audio_files = [os.path.join(self.audio_segments_dir, f"{i}.wav") for i in range(num_segments) if os.path.exists(os.path.join(self.audio_segments_dir, f"{i}.wav"))]
        if not valid_audio_files:
            log.error("No audio files were generated to combine.")
            return False
        if len(valid_audio_files) != num_segments:
            log.warning("Some audio segments failed to generate and will be skipped.")
        try:
            combined_audio = sum(AudioSegment.from_wav(f) for f in tqdm(valid_audio_files, desc="Combining Audio"))
            combined_audio.export(output_path, format="wav")
            log.success(f"All audio segments combined successfully to: {output_path}")
            return True
        except Exception as e:
            log.error(f"Failed to combine audio files: {e}")
            return False

    def _generate_subtitles(self, final_audio_path: str):
        try:
            log.info("\n--- Initializing models for subtitle generation ---")
            model_loader = ModelLoader(config)
            audio_processor = AudioProcessor(model_loader)
            text_processor = TextProcessor(model_loader)
            searcher = Searcher(model_loader, text_processor)
            log.success("Core components for subtitling initialized.")

            original_doc_path = os.path.join(self.doc_cache_dir, "original.txt")
            sentences_path = os.path.join(self.doc_cache_dir, "sentences.txt")
            whisper_cache_path = os.path.join(self.whisper_cache_dir, "transcription.json")
            alignment_cache_path = os.path.join(self.whisper_cache_dir, "aligned.pkl")
            srt_output_path = os.path.join(self.task_dir, "final.srt")

            sentences = self._split_text_into_sentences(original_doc_path, sentences_path)
            whisper_segments = self._transcribe_audio(audio_processor, final_audio_path, whisper_cache_path)
            aligned_data = self._align_text_to_audio(searcher, sentences, whisper_segments, alignment_cache_path)
            self._create_srt_from_alignment(aligned_data, srt_output_path)

        except Exception as e:
            log.error(f"An error occurred during subtitle generation: {e}", exc_info=True)

    def _split_text_into_sentences(self, original_text_path: str, sentences_output_path: str) -> List[str]:
        log.info("\n--- Step 3.1: Splitting text into sentences for alignment ---")
        if os.path.exists(sentences_output_path):
            log.info(f"Found existing sentences cache: {sentences_output_path}")
            with open(sentences_output_path, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f]
        with open(original_text_path, 'r', encoding='utf-8') as f:
            content = f.read()
        sentences = re.split(r'([，。？：,.:?])', content)
        sentences = ["".join(i) for i in zip(sentences[0::2], sentences[1::2])]
        sentences = [s.strip() for s in sentences if s.strip()]
        with open(sentences_output_path, 'w', encoding='utf-8') as f:
            for sentence in sentences:
                f.write(sentence + '\n')
        log.success(f"Split into {len(sentences)} sentences and cached to {sentences_output_path}")
        return sentences

    def _transcribe_audio(self, audio_processor: AudioProcessor, audio_path: str, whisper_cache_path: str) -> List[Dict]:
        log.info("\n--- Step 3.2: Transcribing audio with Whisper ---")
        if os.path.exists(whisper_cache_path):
            log.info(f"Found existing Whisper cache: {whisper_cache_path}")
            with open(whisper_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        log.info(f"Running transcription for {audio_path}...")
        _, whisper_segments, _ = audio_processor.transcribe(audio_path)
        if not whisper_segments:
            raise RuntimeError("Transcription failed, no segments returned.")
        with open(whisper_cache_path, 'w', encoding='utf-8') as f:
            json.dump(whisper_segments, f, ensure_ascii=False, indent=4)
        log.success(f"Transcription saved to {whisper_cache_path}")
        return whisper_segments

    def _align_text_to_audio(self, searcher: Searcher, sentences: List[str], whisper_segments: List[Dict], alignment_cache_path: str) -> List[Dict]:
        log.info("\n--- Step 3.3: Aligning text to audio ---")
        if os.path.exists(alignment_cache_path):
            log.info(f"Found existing alignment cache: {alignment_cache_path}")
            with open(alignment_cache_path, 'rb') as f:
                return pickle.load(f)
        log.info("Running linear alignment...")
        all_whisper_words = [word for segment in whisper_segments for word in segment.get('words', [])]
        aligned_data, _ = searcher.linear_align(sentences, all_whisper_words)
        with open(alignment_cache_path, 'wb') as f:
            pickle.dump(aligned_data, f)
        log.success(f"Alignment data saved to {alignment_cache_path}")
        return aligned_data

    def _create_srt_from_alignment(self, aligned_data: List[Dict], srt_output_path: str):
        log.info("--- Step 3.4: Generating SRT file ---")
        aligned_data.sort(key=lambda x: x['start'])
        punctuations_to_process = "，。？：,.:?"
        with open(srt_output_path, 'w', encoding='utf-8') as f:
            for i, entry in enumerate(aligned_data):
                start_time = TextProcessor.format_time(entry['start'])
                end_time = TextProcessor.format_time(entry['end'])
                text = entry['text']
                for punc in punctuations_to_process:
                    text = text.replace(punc, ' ')
                clean_text = ' '.join(text.split())
                f.write(f"{i + 1}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{clean_text}\n\n")
        log.success(f"Final SRT file generated at: {srt_output_path}")
