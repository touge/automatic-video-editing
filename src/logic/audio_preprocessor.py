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
from src.logger import log
from src.tts import tts
from src.config_loader import config
from src.core.model_loader import ModelLoader
from src.core.text import TextProcessor
from src.core.search import Searcher
from src.core.task_manager import TaskManager
from src.utils import add_line_breaks_after_punctuation # 导入新函数


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
        """
        if not self.whisper_model:
            log.error("Whisper model not available for transcription.")
            return None, None, None

        log.info(f"Transcribing audio file: {audio_file} (this may take a while)...")
        
        segments, info = self.whisper_model.transcribe(
            audio_file, 
            beam_size=5, 
            word_timestamps=True
        )
        
        full_text = ""
        segments_info = []
        
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
            
        log.info("Audio transcription complete.")
        return full_text, segments_info, info


class AudioPreprocessor:
    def __init__(self, task_id: str, doc_file: str, _from_api: bool = False):
        if not task_id or not doc_file:
            raise ValueError("task_id and doc_file must be provided.")
        if not os.path.exists(doc_file):
            raise FileNotFoundError(f"Document file not found at '{doc_file}'")

        self.task_manager = TaskManager(task_id)
        self.doc_file = doc_file
        self.is_api_call = _from_api

    def run(self):
        log.info(f"--- Starting Audio Preprocessing for Task ID: {self.task_manager.task_id} ---")
        
        try:
            # The main run method for the CLI, without custom TTS parameters.
            segments = self._process_document_for_tts()
            if not segments: return

            self._synthesize_audio_segments(segments)
            
            final_audio_path = self.task_manager.get_file_path('final_audio')
            if os.path.exists(final_audio_path):
                log.info(f"Final audio already exists, skipping combination: {final_audio_path}")
            else:
                if not self._combine_audio_segments(len(segments), final_audio_path):
                    # If combination fails, we should also abort.
                    raise RuntimeError("Failed to combine audio segments.")

            self._generate_subtitles(final_audio_path)
        except Exception as e:
            log.error(f"Audio preprocessing pipeline failed: {e}", exc_info=True)
            # Re-raise to ensure the main script knows about the failure.
            raise

    def run_synthesis_only(self, **tts_kwargs) -> str:
        """
        Runs the audio synthesis and combination parts of the pipeline.
        Allows passing custom arguments to the TTS provider.
        Returns the path to the final combined audio file.
        """
        log.info(f"--- Starting Audio Synthesis for Task ID: {self.task_manager.task_id} ---")
        try:
            segments = self._process_document_for_tts()
            if not segments:
                raise ValueError("No text segments found to synthesize.")
            
            self._synthesize_audio_segments(segments, **tts_kwargs)
            
            final_audio_path = self.task_manager.get_file_path('final_audio')
            if not self._combine_audio_segments(len(segments), final_audio_path):
                raise RuntimeError("Failed to combine audio segments.")

            log.success("Audio synthesis and combination completed successfully.")
            return final_audio_path
        except Exception as e:
            log.error(f"Audio synthesis pipeline failed: {e}", exc_info=True)
            raise

    def run_subtitles_generation(self) -> str:
        """
        Runs only the subtitle generation part of the pipeline.
        Assumes that final_audio.wav already exists.
        Returns the path to the final SRT file.
        """
        log.info(f"--- Starting Subtitle Generation for Task ID: {self.task_manager.task_id} ---")
        try:
            final_audio_path = self.task_manager.get_file_path('final_audio')
            if not os.path.exists(final_audio_path):
                raise FileNotFoundError(f"Final audio file not found for this task: {final_audio_path}")
            
            self._generate_subtitles(final_audio_path)
            
            srt_path = self.task_manager.get_file_path('final_srt')
            log.success(f"Subtitle generation completed successfully. SRT file at: {srt_path}")
            return srt_path
        except Exception as e:
            log.error(f"Subtitle generation pipeline failed: {e}", exc_info=True)
            raise

    def save_final_audio(self, audio_content: bytes):
        """
        Saves the provided audio content directly as final_audio.wav, overwriting if it exists.
        """
        final_audio_path = self.task_manager.get_file_path('final_audio')
        with open(final_audio_path, 'wb') as f:
            f.write(audio_content)
        log.info(f"Saved provided audio content to {final_audio_path}")

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
        
        # For the CLI workflow, copy the external script into the task directory.
        # For the API workflow, the script is already in place.
        if not self.is_api_call:
            shutil.copy(self.doc_file, self.task_manager.get_file_path('original_doc'))
            log.success("Cached original document.")

        with open(self.doc_file, 'r', encoding='utf-8') as f:
            content = f.read()
        segments = [seg.strip() for seg in content.split('\n\n') if seg.strip()]
        if not segments:
            log.error("No text segments found for TTS.")
            return []
        log.success(f"Document split into {len(segments)} segments for TTS.")
        for i, segment_text in enumerate(segments):
            with open(self.task_manager.get_file_path('doc_segment', index=i), 'w', encoding='utf-8') as f:
                f.write(segment_text)
        log.success("All TTS text segments cached.")
        return segments

    def _synthesize_audio_segments(self, segments: List[str], **tts_kwargs):
        log.info("--- Step 2.2: Synthesizing audio for each segment ---")
        # Add the task_id to the kwargs for the TTS call, ensuring it's always present.
        tts_kwargs['task_id'] = self.task_manager.task_id

        for i, segment_text in enumerate(tqdm(segments, desc="Synthesizing Audio")):
            audio_segment_path = self.task_manager.get_file_path('audio_segment', index=i)
            if os.path.exists(audio_segment_path):
                continue
            
            try:
                # Pass the combined kwargs to the synthesis function
                response = tts.synthesize(segment_text, **tts_kwargs)
                
                # 检查是返回了URL还是本地路径
                if 'url' in response and response['url']:
                    # 如果是URL，下载文件
                    if not self._download_file(response['url'], audio_segment_path):
                        log.error(f"Failed to download audio for segment {i} from URL: {response['url']}")
                elif 'path' in response and response['path']:
                    # 如果是本地路径，直接移动或复制文件
                    shutil.move(response['path'], audio_segment_path)
                    log.info(f"Moved synthesized audio for segment {i} to final location.")
                else:
                    log.error(f"TTS response for segment {i} is invalid: {response}")

            except Exception as e:
                log.error(f"An error occurred during synthesis for segment {i}: {e}", exc_info=True)
                # Re-raise the exception to halt the process
                raise
        
        log.success("Finished synthesizing all segments.")

    def _combine_audio_segments(self, num_segments: int, output_path: str) -> bool:
        log.info("\n--- Step 2.3: Combining all audio segments ---")
        valid_audio_files = [self.task_manager.get_file_path('audio_segment', index=i) for i in range(num_segments) if os.path.exists(self.task_manager.get_file_path('audio_segment', index=i))]
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

            sentences = self._split_text_into_sentences(
                self.task_manager.get_file_path('original_doc'), 
                self.task_manager.get_file_path('sentences')
            )
            whisper_segments = self._transcribe_audio(
                audio_processor, 
                final_audio_path, 
                self.task_manager.get_file_path('whisper_cache')
            )
            aligned_data = self._align_text_to_audio(
                searcher, 
                sentences, 
                whisper_segments, 
                self.task_manager.get_file_path('alignment_cache')
            )
            self._create_srt_from_alignment(aligned_data, self.task_manager.get_file_path('final_srt'))

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
        # 定义需要添加换行符的标点符号
        punctuations_for_linebreak = ['！', '？', '。', '…']
        
        with open(srt_output_path, 'w', encoding='utf-8') as f:
            for i, entry in enumerate(aligned_data):
                start_time = TextProcessor.format_time(entry['start'])
                end_time = TextProcessor.format_time(entry['end'])
                text = entry['text']
                
                # 在指定标点符号后添加换行符
                processed_text = add_line_breaks_after_punctuation(text, punctuations_for_linebreak)
                
                # 移除其他不需要的标点符号或多余空格（如果需要）
                # 这里假设 add_line_breaks_after_punctuation 已经处理了主要格式
                # 如果还需要进一步清理，可以在这里添加
                
                f.write(f"{i + 1}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{processed_text.strip()}\n\n") # 使用处理后的文本，并去除首尾空白
        log.success(f"Final SRT file generated at: {srt_output_path}")
