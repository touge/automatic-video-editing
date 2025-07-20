import os
import json
from tqdm import tqdm
from typing import List, Dict, Any

from src.config_loader import config
from src.logic.scene_generator import SceneGenerator
from src.core.asset_manager import AssetManager
from src.core.video_composer import VideoComposer as CoreVideoComposer
from src.logger import log
from src.core.task_manager import TaskManager
from src.utils import get_video_duration

class VideoCompositionLogic:
    def __init__(self, task_id: str):
        if not task_id:
            raise ValueError("A task_id must be provided.")
        
        self.task_manager = TaskManager(task_id)
        self.core_composer = CoreVideoComposer(config, task_id)

    def prepare_all_assets(self):
        """
        Step 1: Finds assets for all sub-scenes and saves the result to a new file.
        """
        log.info(f"--- Starting Asset Preparation for Task ID: {self.task_manager.task_id} ---")

        # Input for this step
        scenes_path = self.task_manager.get_file_path('final_scenes')
        if not os.path.exists(scenes_path):
            raise FileNotFoundError(f"Required file 'final_scenes.json' not found.")

        main_scenes = SceneGenerator.load_final_scenes(self.task_manager.task_id)
        if not main_scenes:
            raise ValueError("Failed to load or parse 'final_scenes.json'.")

        # The core asset finding logic
        scenes_with_assets, all_found = self._find_assets_for_sub_scenes(main_scenes)
        
        if not all_found:
            # The method already logs the specific error, so we just raise a generic failure
            raise RuntimeError("Failed to find assets for all sub-scenes.")

        # Clean the data for saving
        cleaned_scenes = self._clean_runtime_data(scenes_with_assets)
        
        # Output of this step
        assets_scenes_path = self.task_manager.get_file_path('final_scenes_with_assets')
        with open(assets_scenes_path, 'w', encoding='utf-8') as f:
            json.dump(cleaned_scenes, f, ensure_ascii=False, indent=2)
        
        log.success(f"Asset preparation complete. Data saved to {assets_scenes_path}")

    def run_assembly_stage(self, stage: str, burn_subtitle: bool):
        """
        Step 2: Runs a specific stage of the video assembly process.
        """
        log.info(f"--- Starting Assembly Stage '{stage}' for Task ID: {self.task_manager.task_id} ---")

        # Input for this step
        assets_scenes_path = self.task_manager.get_file_path('final_scenes_with_assets')
        audio_path = self.task_manager.get_file_path('final_audio')

        if not os.path.exists(assets_scenes_path):
            raise FileNotFoundError(f"Required file 'final_scenes_assets.json' not found.")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Required file 'final_audio.wav' not found.")

        with open(assets_scenes_path, 'r', encoding='utf-8') as f:
            scenes_with_assets = json.load(f)
        
        all_sub_scenes = [
            sub_scene
            for main_scene in scenes_with_assets
            for sub_scene in main_scene.get('scenes', [])
        ]

        # --- Execute assembly stages ---
        
        processed_segments = self.core_composer.prepare_and_normalize_all_segments(all_sub_scenes)
        
        concatenated_video_path = self.core_composer.concatenate_segments(processed_segments)
        if stage == "silent":
            log.success(f"Silent video assembly complete. Output: {concatenated_video_path}")
            return concatenated_video_path

        video_with_audio_path = self.core_composer.merge_audio(concatenated_video_path, audio_path)
        if stage == "audio":
            log.success(f"Video with audio assembly complete. Output: {video_with_audio_path}")
            return video_with_audio_path

        if burn_subtitle:
            final_video_path = self.core_composer.burn_subtitles_to_video(video_with_audio_path)
        else:
            final_video_path = self.task_manager.get_file_path('final_video')
            shutil.copy(video_with_audio_path, final_video_path)

        log.success(f"Full video assembly complete. Output: {final_video_path}")
        return final_video_path

    def _find_assets_for_sub_scenes(self, main_scenes: list) -> tuple[list, bool]:
        asset_manager = AssetManager(config, self.task_manager.task_id)
        
        all_sub_scenes = [
            sub_scene
            for main_scene in main_scenes
            for sub_scene in main_scene.get('scenes', [])
        ]
        
        sub_scenes_iterable = tqdm(all_sub_scenes, desc="Finding Assets", unit="sub-scene")
        online_search_count = config.get('asset_search', {}).get('online_search_count', 10)

        for i, sub_scene in enumerate(sub_scenes_iterable):
            sub_scenes_iterable.set_description(f"Finding Asset {i+1}/{len(all_sub_scenes)}\n")
            
            keywords = sub_scene.get('keys', [])
            if not keywords:
                log.error(f"Sub-scene {i+1} is missing keywords. Aborting.")
                return main_scenes, False

            if sub_scene.get('asset_path') and os.path.exists(sub_scene.get('asset_path')):
                log.debug(f"Found cached asset for sub-scene {i+1}")
                continue

            found_video_info_list = asset_manager.find_assets_for_scene(sub_scene, online_search_count)
            
            if not found_video_info_list:
                # AssetManager 已经记录了详细的错误日志，这里直接返回失败
                return main_scenes, False

            # AssetManager 返回的是包含单个已验证素材信息的列表
            video_info = found_video_info_list[0]
            
            # 更新子场景信息
            sub_scene['asset_path'] = video_info['local_path'].replace(os.sep, '/')
            # AssetManager 现在不返回时长，我们需要自己获取
            sub_scene['actual_duration'] = get_video_duration(video_info['local_path'])
        
        return main_scenes, True

    def _clean_runtime_data(self, main_scenes: list) -> list:
        """Removes temporary runtime fields from scene data before saving."""
        import copy
        scenes_copy = copy.deepcopy(main_scenes)
        keys_to_remove = ['actual_duration']
        for main_scene in scenes_copy:
            for sub_scene in main_scene.get('scenes', []):
                for key in keys_to_remove:
                    if key in sub_scene:
                        del sub_scene[key]
        return scenes_copy
