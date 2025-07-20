import os
import math
from tqdm import tqdm

from src.config_loader import config
from src.logic.scene_generator import SceneGenerator
from src.core.asset_manager import AssetManager
from src.core.video_composer import VideoComposer as CoreVideoComposer
from src.logger import log
from src.core.task_manager import TaskManager
from src.utils import get_video_duration # Import get_video_duration
from typing import List, Dict, Any # Import for type hinting

class VideoComposition:
    def __init__(self, task_id: str, burn_subtitle: bool = False, scene_config: dict = None):
        if not task_id:
            raise ValueError("A task_id must be provided.")
        
        self.task_manager = TaskManager(task_id)
        self.burn_subtitle = burn_subtitle
        self.scene_config = scene_config if scene_config is not None else {}

    def run(self):
        log.info(f"--- Starting Video Composition for Task ID: {self.task_manager.task_id} ---")

        scenes_path = self.task_manager.get_file_path('final_scenes')
        audio_path = self.task_manager.get_file_path('final_audio')

        if not os.path.exists(scenes_path) or not os.path.exists(audio_path):
            log.error(f"Required files (final_scenes.json or final_audio.wav) not found in task directory: {self.task_manager.task_path}")
            return

        # 1. Load scenes
        scenes = SceneGenerator.load_final_scenes(self.task_manager.task_id)
        if not scenes:
            return

        # 2. Find assets for each sub-scene
        scenes_with_assets, all_assets_found, scenes_updated = self._find_assets_for_sub_scenes(scenes, self.scene_config)
        if not all_assets_found:
            log.error("Could not find assets for all sub-scenes. Aborting composition.")
            return
        
        # 3. 准备场景和资源路径数据
        processed_sub_scenes = []
        scene_asset_paths = []
        
        for scene_idx, main_scene in enumerate(scenes_with_assets):
            for sub_scene in main_scene.get('scenes', []):
                # Only process sub-scenes that have a verified asset path
                if sub_scene.get('asset_verified') and 'asset_path' in sub_scene and os.path.exists(sub_scene['asset_path']):
                    # Ensure sub_scene has all necessary properties for CoreVideoComposer
                    sub_scene.update({
                        'duration': sub_scene.get('time', 5.0), # Use 'time' field as required duration
                        'start_time': sub_scene.get('start', 0), # Use 'start' field
                        'text': sub_scene.get('text', ''),
                        'scene_index': scene_idx
                    })
                    processed_sub_scenes.append(sub_scene)
                    scene_asset_paths.append([sub_scene['asset_path']])
                    log.debug(f"主场景 {scene_idx}: 添加资源 {sub_scene['asset_path']}")
                else:
                    log.warning(f"主场景 {scene_idx}: 跳过无效或未找到资源的子场景")
        
        if not processed_sub_scenes:
            log.error("没有找到有效的视频资源，无法进行合成。")
            return
        
        log.info(f"准备合成 {len(processed_sub_scenes)} 个视频片段")
        
        try:
            # 4. 组装最终视频
            composer = CoreVideoComposer(config, self.task_manager.task_id)
            composer.assemble_video(
                scenes=processed_sub_scenes, # Pass processed sub-scenes with extension info
                scene_asset_paths=scene_asset_paths, # This still just passes the raw paths
                audio_path=audio_path,
                burn_subtitle=self.burn_subtitle
            )

            # 5. 只有在视频合成完全成功后，才保存更新
            if scenes_updated:
                log.info("视频合成成功，正在保存更新后的场景文件...")
                cleaned_scenes = self._clean_scene_data(scenes_with_assets)
                SceneGenerator.save_final_scenes(cleaned_scenes, self.task_manager.task_id)

        except Exception as e:
            log.error(f"视频组装步骤失败，已中止，不会保存场景文件。错误: {e}", exc_info=True)
            self.task_manager.update_task_status(
                self.task_manager.STATUS_FAILED,
                step="video_composition",
                details={"error": str(e)}
            )
            # 发生错误时，不执行任何后续操作，直接退出
            return

    def _clean_scene_data(self, main_scenes: list) -> list:
        """在保存前，从场景数据中移除临时的运行时字段。"""
        import copy
        scenes_copy = copy.deepcopy(main_scenes)
        # Define keys to remove from sub-scenes during cleanup
        keys_to_remove = ['main_scene_index', 'sub_scene_index', 'asset_verified', 'duration', 'start_time', 'text', 'actual_duration', 'extend_method', 'extend_duration']
        for main_scene in scenes_copy:
            for sub_scene in main_scene.get('scenes', []):
                for key in keys_to_remove:
                    if key in sub_scene:
                        del sub_scene[key]
        return scenes_copy

    def _find_assets_for_sub_scenes(self, main_scenes: list, scene_config: dict) -> tuple[list, bool, bool]:
        log.info("--- Step 1: Finding assets for each sub-scene ---")
        asset_manager = AssetManager(config, self.task_manager.task_id)
        scenes_updated = False

        all_sub_scenes = [
            sub_scene
            for main_scene in main_scenes
            for sub_scene in main_scene.get('scenes', [])
        ]
        
        log.debug(f"Total sub-scenes to process: {len(all_sub_scenes)}")
        sub_scenes_iterable = tqdm(all_sub_scenes, desc="Finding Assets", unit="sub-scene")
        
        online_search_count = config.get('asset_search', {}).get('online_search_count', 10)

        for i, sub_scene in enumerate(sub_scenes_iterable):
            sub_scenes_iterable.set_description(f"Finding Asset {i+1}/{len(all_sub_scenes)}")
            
            # Cleaned up logging
            log.debug(f"\nProcessing sub-scene {i+1}: \"{sub_scene.get('source_text', '')[:30]}...\"")
            
            keywords = sub_scene.get('keys', [])
            if not keywords:
                log.error(f"Sub-scene {i+1} is missing keywords. Aborting.")
                return main_scenes, False, scenes_updated

            # --- Simplified Cache Check ---
            cached_asset_path = sub_scene.get('asset_path')
            if cached_asset_path and os.path.exists(cached_asset_path):
                log.debug(f"Found cached asset: {cached_asset_path}")
                sub_scene['asset_verified'] = True
                continue

            # --- Find ONE new asset ---
            candidate_video_infos = asset_manager.find_assets_for_scene(sub_scene, online_search_count)
            
            if not candidate_video_infos:
                log.error(f"Asset search failed for sub-scene {i+1} with keywords {keywords}. Aborting task.")
                # Fail Fast: if no asset is found, the whole process fails.
                return main_scenes, False, scenes_updated

            # --- Process the SINGLE found asset ---
            video_info = candidate_video_infos[0]
            asset_path = video_info.get('local_path')
            actual_duration = video_info.get('duration')

            if not asset_path or not os.path.exists(asset_path) or actual_duration is None:
                 log.error(f"Found asset for sub-scene {i+1} is invalid. Aborting.")
                 return main_scenes, False, scenes_updated

            # --- Asset is valid, update sub_scene ---
            sub_scene['asset_path'] = asset_path.replace(os.sep, '/')
            sub_scene['actual_duration'] = actual_duration
            sub_scene['asset_verified'] = True
            scenes_updated = True
            log.success(f"Successfully found and verified asset for sub-scene {i+1}: {asset_path}")

        log.info("All sub-scenes have successfully found an asset.")
        return main_scenes, True, scenes_updated
