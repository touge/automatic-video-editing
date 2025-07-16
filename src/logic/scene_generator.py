import os
import json
from tqdm import tqdm
from pathlib import Path

from src.config_loader import config
from src.subtitle_parser import parse_srt_file
from src.core.scene_splitter import SceneSplitter
from src.keyword_generator import KeywordGenerator
from src.logger import log
from src.core.task_manager import TaskManager

class SceneGenerator:
    @classmethod
    def load_final_scenes(cls, task_id: str) -> list:
        task_manager = TaskManager(task_id)
        final_scenes_path = task_manager.get_file_path('final_scenes')
        
        if not os.path.exists(final_scenes_path):
            log.error(f"Final scenes file does not exist: {final_scenes_path}")
            return []
            
        try:
            with open(final_scenes_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Error loading final scenes data: {e}")
            return []
        
    @classmethod
    def save_final_scenes(cls, scenes: list, task_id: str) -> bool:
        task_manager = TaskManager(task_id)
        final_scenes_path = task_manager.get_file_path('final_scenes')
        try:
            with open(final_scenes_path, 'w', encoding='utf-8') as f:
                json.dump(scenes, f, ensure_ascii=False, indent=2)
            log.info(f"Final scenes data saved to: {final_scenes_path}")
            return True
        except Exception as e:
            log.error(f"Error saving final scenes data: {e}")
            return False

    def __init__(self, task_id: str):
        if not task_id:
            raise ValueError("A task_id must be provided.")
        
        self.task_manager = TaskManager(task_id)

    def run(self):
        log.info(f"--- Starting Scene Generation for Task ID: {self.task_manager.task_id} ---")

        final_scenes_path = self.task_manager.get_file_path('final_scenes')
        if os.path.exists(final_scenes_path):
            log.success(f"Final scenes file already exists for task {self.task_manager.task_id}. Nothing to do.")
            log.info(f"You can find the file at: {final_scenes_path}")
            return

        srt_path = self.task_manager.get_file_path('final_srt')
        if not os.path.exists(srt_path):
            log.error(f"SRT file not found for this task: {srt_path}")
            return

        segments = self._parse_srt()
        if not segments: return

        raw_scenes = self._split_scenes(segments)
        if not raw_scenes: return
        
        scenes_with_keywords = self._generate_keywords_for_scenes(raw_scenes)
        if not scenes_with_keywords: return

        self.save_final_scenes(scenes_with_keywords, self.task_manager.task_id)

        log.info("############################################################")
        log.success(f"Scene generation and keyword analysis complete!")
        log.info(f"Task ID: {self.task_manager.task_id}")
        log.info(f"Final scenes with keywords saved to: {final_scenes_path}")
        log.info("Next, you can manually review the final_scenes.json file or proceed to the final composition step.")
        log.info("############################################################")

    def _generate_keywords_for_scenes(self, scenes: list) -> list:
        log.info("--- Step 3: Generating keywords for each scene ---")
        keyword_gen = KeywordGenerator(config)
        scenes_iterable = tqdm(scenes, desc="Generating Keywords", unit="scene")
        
        keyword_gen.generate_for_scenes(scenes_iterable)
        
        log.success("Keyword generation complete.")
        return scenes

    def _parse_srt(self) -> list:
        log.info("\n--- Step 1: Parsing SRT file ---")
        segments_cache_path = self.task_manager.get_file_path('segments_cache')
        if os.path.exists(segments_cache_path):
            log.info(f"Found cache, loading segments from {Path(segments_cache_path).name}...")
            with open(segments_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        segments = parse_srt_file(self.task_manager.get_file_path('final_srt'))
        if not segments:
            log.error("Failed to parse any segments from the SRT file.")
            return []
            
        log.success(f"Parsed {len(segments)} segments, caching to {Path(segments_cache_path).name}...")
        with open(segments_cache_path, 'w', encoding='utf-8') as f:
            json.dump(segments, f, ensure_ascii=False, indent=4)
        return segments

    def _split_scenes(self, segments: list) -> list:
        log.info("\n--- Step 2: Splitting segments into scenes ---")
        scenes_raw_cache_path = self.task_manager.get_file_path('scenes_raw_cache')
        if os.path.exists(scenes_raw_cache_path):
            log.info(f"Found cache, loading raw scenes from {Path(scenes_raw_cache_path).name}...")
            with open(scenes_raw_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        splitter = SceneSplitter(config, self.task_manager.task_id)
        initial_scenes = splitter.split(segments)

        if not initial_scenes:
            log.error("AI failed to split scenes.")
            return []
        
        log.success(f"AI initially split into {len(initial_scenes)} scenes.")
        log.info("Post-processing scenes to optimize duration...")
        
        min_duration = config.get("video.min_clip_duration", 3.0)
        max_duration = config.get("video.max_clip_duration", 8.0) * 2.5
        
        processed_scenes = self._post_process_scenes(initial_scenes, min_duration, max_duration)
        log.success(f"Post-processing complete. Final scene count: {len(processed_scenes)}.")

        log.info(f"Caching processed scenes to {Path(scenes_raw_cache_path).name}...")
        with open(scenes_raw_cache_path, 'w', encoding='utf-8') as f:
            json.dump(processed_scenes, f, ensure_ascii=False, indent=4)
        
        return processed_scenes

    def _post_process_scenes(self, scenes: list, min_duration: float, max_duration: float) -> list:
        merged_scenes = []
        buffer = None
        for scene in scenes:
            if buffer is None:
                buffer = scene.copy()
                continue
            if buffer['duration'] < min_duration:
                buffer['text'] += f" {scene['text']}"
                buffer['scene_end'] = scene['scene_end']
                buffer['duration'] = buffer['scene_end'] - buffer['scene_start']
                if 'segments' in buffer and 'segments' in scene:
                     buffer['segments'].extend(scene['segments'])
            else:
                merged_scenes.append(buffer)
                buffer = scene.copy()
        if buffer:
            merged_scenes.append(buffer)
        
        final_scenes = []
        for scene in merged_scenes:
            if scene['duration'] > max_duration:
                log.warning(f"Scene is too long ({scene['duration']:.2f}s), simple split applied.")
                final_scenes.append(scene)
            else:
                final_scenes.append(scene)
        return final_scenes
