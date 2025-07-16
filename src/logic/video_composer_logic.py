import os
import math
from tqdm import tqdm

from src.config_loader import config
from src.logic.scene_generator import SceneGenerator
from src.core.asset_manager import AssetManager
from src.core.video_composer import VideoComposer as CoreVideoComposer
from src.logger import log
from src.core.task_manager import TaskManager

class VideoComposition:
    def __init__(self, task_id: str, burn_subtitle: bool = False):
        if not task_id:
            raise ValueError("A task_id must be provided.")
        
        self.task_manager = TaskManager(task_id)
        self.burn_subtitle = burn_subtitle
        
        # Paths are now managed by TaskManager using the new method
        self.scenes_path = self.task_manager.get_file_path('final_scenes')
        self.audio_path = self.task_manager.get_file_path('final_audio')
        self.subtitle_path = self.task_manager.get_file_path('final_srt')

    def run(self):
        log.info(f"--- Starting Video Composition for Task ID: {self.task_manager.task_id} ---")

        if not os.path.exists(self.scenes_path) or not os.path.exists(self.audio_path):
            log.error(f"Required files (scenes.json or final_audio.wav) not found in task directory: {self.task_manager.task_path}")
            return

        # 1. Load scenes
        scenes = SceneGenerator.load_final_scenes(self.task_manager.task_id)
        if not scenes:
            return

        # 2. Find assets for each scene
        scenes_with_assets, all_assets_found, scenes_updated = self._find_assets_for_scenes(scenes)
        if not all_assets_found:
            log.error("Could not find assets for all scenes. Aborting composition.")
            return
        
        # 3. Compose the final video
        composer = CoreVideoComposer(config, self.task_manager.task_id)
        composer.assemble_video(
            scenes=scenes_with_assets,
            scene_asset_paths=[scene.get('asset_paths', []) for scene in scenes_with_assets],
            audio_path=self.audio_path,
            burn_subtitle=self.burn_subtitle
        )

        # Save updated scenes if assets were found
        if scenes_updated:
            SceneGenerator.save_final_scenes(scenes_with_assets, self.task_manager.task_id)

    def _split_scene_duration(self, total_duration: float, max_clip_duration: float, min_clip_duration: float) -> list[float]:
        if total_duration <= max_clip_duration:
            return [round(total_duration, 2)]
        num_clips = math.ceil(total_duration / max_clip_duration)
        if total_duration / num_clips < min_clip_duration:
            num_clips = math.floor(total_duration / min_clip_duration)
            if num_clips == 0:
                return [round(total_duration, 2)]
        if num_clips == 1:
            return [round(total_duration, 2)]
        durations = []
        remaining_duration = total_duration
        for i in range(num_clips):
            clips_to_go = num_clips - i
            if clips_to_go == 1:
                durations.append(remaining_duration)
                break
            max_possible_duration = remaining_duration - (clips_to_go - 1) * min_clip_duration
            current_duration = min(max_clip_duration, max_possible_duration)
            durations.append(current_duration)
            remaining_duration -= current_duration
        return [round(d, 2) for d in durations]

    def _find_assets_for_scenes(self, scenes: list) -> tuple[list, bool, bool]:
        log.info("--- Step 1: Finding assets for scenes ---")
        video_config = config.get('video', {})
        max_clip_duration = video_config.get('max_clip_duration', 8.0)
        min_clip_duration = video_config.get('min_clip_duration', 3.0)
        
        log.debug(f"视频配置: max_clip_duration={max_clip_duration}, min_clip_duration={min_clip_duration}")

        asset_manager = AssetManager(config, self.task_manager.task_id)
        all_assets_found = True
        scenes_updated = False

        scenes_iterable = tqdm(scenes, desc="Finding Assets", unit="scene")
        for i, scene in enumerate(scenes_iterable):
            log.debug(f"处理场景 {i+1}:")
            log.debug(f"场景文本: {scene['text']}")
            log.debug(f"场景持续时间: {scene['duration']}")
            
            duration_parts = self._split_scene_duration(
                scene['duration'], 
                max_clip_duration, 
                min_clip_duration
            )
            scene['duration_parts'] = duration_parts
            num_assets_needed = len(duration_parts)
            
            cached_asset_paths = scene.get('asset_paths', [])
            if cached_asset_paths and len(cached_asset_paths) == num_assets_needed and all(os.path.exists(p) for p in cached_asset_paths):
                continue

            asset_paths = asset_manager.find_assets_for_scene(scene, num_assets_needed)
            log.debug(f"找到的资源路径: {asset_paths}")
            
            if not asset_paths or len(asset_paths) < num_assets_needed:
                log.error(f"Failed to find enough assets for scene {i+1}: \"{scene['text']}\"")
                all_assets_found = False
                break
            
            scene['asset_paths'] = asset_paths
            scenes_updated = True

        if scenes_updated:
            log.info("Asset paths updated, saving back to scenes.json...")
            SceneGenerator.save_final_scenes(scenes, self.task_manager.task_id)

        return scenes, all_assets_found, scenes_updated
