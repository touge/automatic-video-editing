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

        # 2. Find assets for each sub-scene (shot)
        scenes_with_assets, all_assets_found, scenes_updated = self._find_assets_for_shots(scenes, self.scene_config)
        if not all_assets_found:
            log.error("Could not find assets for all shots. Aborting composition.")
            return
        
        # 3. 准备场景和资源路径数据
        processed_scenes = []
        scene_asset_paths = []
        
        for scene_idx, scene in enumerate(scenes_with_assets):
            for shot in scene.get('scenes', []):
                if 'asset_path' in shot and os.path.exists(shot['asset_path']):
                    # 确保场景有所有必要的属性
                    shot.update({
                        'duration': shot.get('time', 5.0), # 使用 'time' 字段作为时长
                        'start_time': shot.get('start_time', 0),
                        'text': shot.get('text', ''),
                        'scene_index': scene_idx
                    })
                    processed_scenes.append(shot)
                    scene_asset_paths.append([shot['asset_path']])
                    log.debug(f"场景 {scene_idx}: 添加资源 {shot['asset_path']}")
                else:
                    log.warning(f"场景 {scene_idx}: 跳过无效资源的镜头")
        
        if not processed_scenes:
            log.error("没有找到有效的视频资源")
            return
        
        log.info(f"准备合成 {len(processed_scenes)} 个视频片段")
        
        try:
            # 4. 组装最终视频
            composer = CoreVideoComposer(config, self.task_manager.task_id)
            composer.assemble_video(
                scenes=processed_scenes,
                scene_asset_paths=scene_asset_paths,
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
            # 发生错误时，不执行任何后续操作，直接退出
            return

    def _clean_scene_data(self, scenes: list) -> list:
        """在保存前，从场景数据中移除临时的运行时字段。"""
        import copy
        scenes_copy = copy.deepcopy(scenes)
        keys_to_remove = ['parent_scene_text', 'scene_index', 'shot_index', 'asset_verified', 'duration', 'start_time', 'text']
        for scene in scenes_copy:
            for shot in scene.get('scenes', []):
                for key in keys_to_remove:
                    if key in shot:
                        del shot[key]
        return scenes_copy

    def _find_assets_for_shots(self, scenes: list, scene_config: dict) -> tuple[list, bool, bool]:
        log.info("--- Step 1: Finding assets for each shot ---")
        asset_manager = AssetManager(config, self.task_manager.task_id)
        all_assets_found = True
        scenes_updated = False

        # 添加调试信息
        log.debug(f"处理 {len(scenes)} 个主场景")
        total_shots = sum(len(scene.get('scenes', [])) for scene in scenes)
        log.debug(f"总计 {total_shots} 个子场景需要处理")

        # 创建扁平化的镜头列表用于进度条显示
        all_shots = []
        for scene_idx, scene in enumerate(scenes):
            for shot_idx, shot in enumerate(scene.get('scenes', [])):
                # 添加更多上下文信息
                shot.update({
                    'parent_scene_text': scene['text'],
                    'scene_index': scene_idx,
                    'shot_index': shot_idx
                })
                all_shots.append(shot)

        shots_iterable = tqdm(all_shots, desc="Finding Assets", unit="shot")
        for shot in shots_iterable:
            # 详细的调试信息
            log.debug(f"\n处理镜头: Scene {shot['scene_index']}, Shot {shot['shot_index']}")
            log.debug(f"场景文本: {shot['parent_scene_text']}")
            
            keywords = shot.get('keys', shot.get('keywords_en', []))
            if not keywords:
                log.warning(f"镜头缺少关键词: {shot}")
                continue

            # 检查缓存的资源路径
            cached_asset_path = shot.get('asset_path')
            if cached_asset_path and os.path.exists(cached_asset_path):
                log.debug(f"使用缓存资源: {cached_asset_path}")
                continue

            # 为 asset_manager 构建一个临时的 scene-like 字典
            # 优先使用子场景的 source_text，如果不存在，则回退到父场景的文本
            context_text = shot.get('source_text', shot.get('parent_scene_text', ''))
            temp_scene_for_asset_manager = {
                "keywords_en": keywords,
                "text": context_text
            }

            # 查找资源
            found_assets = asset_manager.find_assets_for_scene(temp_scene_for_asset_manager, 1)
            
            if not found_assets:
                log.error(f"无法找到资源，参数: {temp_scene_for_asset_manager}")
                all_assets_found = False
                break
            
            # 验证资源
            asset_path = found_assets[0]
            if not os.path.exists(asset_path):
                log.error(f"资源文件不存在: {asset_path}")
                all_assets_found = False
                break
            
            # 保存资源路径
            shot['asset_path'] = asset_path
            shot['asset_verified'] = True  # 添加验证标记
            scenes_updated = True
            
            log.debug(f"找到有效资源: {asset_path}")

        # 最终验证
        if all_assets_found:
            valid_shots = sum(1 for shot in all_shots if shot.get('asset_verified'))
            log.info(f"成功处理 {valid_shots}/{len(all_shots)} 个镜头")
        else:
            log.error("部分镜头未能找到合适的资源")

        return scenes, all_assets_found, scenes_updated
