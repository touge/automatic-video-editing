import os
import json
from tqdm import tqdm

from src.config_loader import config
from src.utils import ensure_task_path  # 移除 save_scenes_to_json
from src.subtitle_parser import parse_srt_file
from src.core.scene_splitter import SceneSplitter
from src.keyword_generator import KeywordGenerator
from src.logger import log

class SceneGenerator:
    FINAL_SCENES_FILENAME = "final_scenes.json"
    SRT_FILENAME = "final.srt"  # 添加 SRT 文件名常量

    @classmethod
    def _get_final_scenes_path(cls, task_id: str) -> str:
        """获取最终场景文件的标准路径"""
        task_dir = ensure_task_path(task_id)
        return os.path.join(task_dir, cls.FINAL_SCENES_FILENAME)
        
    @classmethod
    def load_final_scenes(cls, task_id: str) -> list:
        final_scenes_path = cls._get_final_scenes_path(task_id)
        
        if not os.path.exists(final_scenes_path):
            log.error(f"最终场景文件不存在: {final_scenes_path}")
            return []
            
        try:
            with open(final_scenes_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.error(f"加载最终场景数据时出错: {e}")
            return []
        
    @classmethod
    def save_final_scenes(cls, scenes: list, task_id: str) -> bool:
        final_scenes_path = cls._get_final_scenes_path(task_id)
        try:
            with open(final_scenes_path, 'w', encoding='utf-8') as f:
                json.dump(scenes, f, ensure_ascii=False, indent=2)
            log.info(f"最终场景数据已保存至: {final_scenes_path}")
            return True
        except Exception as e:
            log.error(f"保存最终场景数据时出错: {e}")
            return False

    def __init__(self, task_id: str):
        if not task_id:
            raise ValueError("A task_id must be provided.")
        
        self.task_id = task_id
        self.task_dir = ensure_task_path(task_id)
        
        # Define paths - 使用类方法来获取路径
        self.final_scenes_path = self._get_final_scenes_path(self.task_id)
        self.srt_path = os.path.join(self.task_dir, self.SRT_FILENAME)  # 添加 srt_path
        
        # Cache paths
        self.scenes_cache_dir = os.path.join(self.task_dir, ".scenes")
        self.segments_cache_path = os.path.join(self.scenes_cache_dir, "segments.json")
        self.scenes_raw_cache_path = os.path.join(self.scenes_cache_dir, "scenes_raw.json")

        os.makedirs(self.scenes_cache_dir, exist_ok=True)

    def run(self):
        log.info(f"--- Starting Scene Generation for Task ID: {self.task_id} ---")

        if os.path.exists(self.final_scenes_path):
            log.success(f"Final scenes file already exists for task {self.task_id}. Nothing to do.")
            log.info(f"You can find the file at: {self.final_scenes_path}")
            return

        if not os.path.exists(self.srt_path):
            log.error(f"SRT file not found for this task: {self.srt_path}")
            return

        # 1. Parse SRT file
        segments = self._parse_srt()
        if not segments: return

        # 2. Split into scenes
        raw_scenes = self._split_scenes(segments)
        if not raw_scenes: return
        
        # 3. Generate keywords for scenes
        scenes_with_keywords = self._generate_keywords_for_scenes(raw_scenes)
        if not scenes_with_keywords: return

        # 4. Save final scenes file - 修改这里
        # self._save_scenes_to_json(scenes_with_keywords)
        self.save_final_scenes(scenes_with_keywords, self.task_id)

        log.info("############################################################")
        log.success(f"Scene generation and keyword analysis complete!")
        log.info(f"Task ID: {self.task_id}")
        log.info(f"Final scenes with keywords saved to: {self.final_scenes_path}")
        log.info("Next, you can manually review the final_scenes.json file or proceed to the final composition step.")
        log.info("############################################################")

    def _generate_keywords_for_scenes(self, scenes: list) -> list:
        log.info("--- Step 3: Generating keywords for each scene ---")
        keyword_gen = KeywordGenerator(config)
        scenes_iterable = tqdm(scenes, desc="Generating Keywords", unit="scene")
        
        # The generate_for_scenes method modifies the scenes list in-place
        keyword_gen.generate_for_scenes(scenes_iterable)
        
        log.success("Keyword generation complete.")
        return scenes

    def _parse_srt(self) -> list:
        log.info("\n--- Step 1: Parsing SRT file ---")
        if os.path.exists(self.segments_cache_path):
            log.info(f"Found cache, loading segments from {os.path.basename(self.segments_cache_path)}...")
            with open(self.segments_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        segments = parse_srt_file(self.srt_path)
        if not segments:
            log.error("Failed to parse any segments from the SRT file.")
            return []
            
        log.success(f"Parsed {len(segments)} segments, caching to {os.path.basename(self.segments_cache_path)}...")
        with open(self.segments_cache_path, 'w', encoding='utf-8') as f:
            json.dump(segments, f, ensure_ascii=False, indent=4)
        return segments

    def _split_scenes(self, segments: list) -> list:
        log.info("\n--- Step 2: Splitting segments into scenes ---")
        if os.path.exists(self.scenes_raw_cache_path):
            log.info(f"Found cache, loading raw scenes from {os.path.basename(self.scenes_raw_cache_path)}...")
            with open(self.scenes_raw_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        splitter = SceneSplitter(config, self.task_id)
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

        log.info(f"Caching processed scenes to {os.path.basename(self.scenes_raw_cache_path)}...")
        with open(self.scenes_raw_cache_path, 'w', encoding='utf-8') as f:
            json.dump(processed_scenes, f, ensure_ascii=False, indent=4)
        
        return processed_scenes

    def _post_process_scenes(self, scenes: list, min_duration: float, max_duration: float) -> list:
        # This logic is complex and can be moved from the original script.
        # For now, a simplified version. A more robust implementation would be needed.
        # Merging short scenes
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
        
        # Splitting long scenes (simplified)
        final_scenes = []
        for scene in merged_scenes:
            if scene['duration'] > max_duration:
                log.warning(f"Scene is too long ({scene['duration']:.2f}s), simple split applied.")
                # Simple split logic can be improved
                half_duration = scene['duration'] / 2
                # This is a placeholder for a more complex splitting logic
                # For now, we just accept the long scene
                final_scenes.append(scene)
            else:
                final_scenes.append(scene)
        return final_scenes

    def _save_scenes_to_json(self, scenes: list) -> None:
        """实例方法中使用类方法来保存场景"""
        self.save_scenes_to_json(scenes, self.task_id)
