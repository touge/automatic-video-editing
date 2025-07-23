import os
import json
import shutil
from tqdm import tqdm
from typing import List, Dict, Any

from src.config_loader import config
from src.core.asset_manager import AssetManager
from src.core.video_composer import VideoComposer as CoreVideoComposer
from src.core.frame_accurate_video_composer import FrameAccurateVideoComposer
from src.logger import log
from src.core.task_manager import TaskManager
from src.utils import get_video_duration

class VideoGenerator:
    def __init__(self, task_id: str):
        if not task_id:
            raise ValueError("A task_id must be provided.")
        
        self.task_manager = TaskManager(task_id)
        self.core_composer = CoreVideoComposer(config, task_id)

        self.final_video_path = self.task_manager.get_file_path('final_video')

    def _run_frame_accurate_composition(self) -> str:
        log.info("--- Invoking Frame-Accurate Video Composer ---")

        if os.path.exists(self.final_video_path):
            log.success(f"The final video file for task {self.task_manager.task_id} already exists. No action is required.")
            log.info(f"You can find the file at: {self.final_video_path}")
            return self.final_video_path

        assets_scenes_path = self.task_manager.get_file_path('final_scenes_with_assets')
        audio_path = self.task_manager.get_file_path('final_audio')

        # 新合成器的输出是带有音频的视频，作为后续烧录字幕的输入
        output_path = self.task_manager.get_file_path('video_with_audio')

        # 从已知文件路径反推任务目录，避免直接访问不存在的属性
        task_dir = os.path.dirname(assets_scenes_path)
        temp_dir = os.path.join(task_dir, "composition_temp")

        # 从全局配置中读取参数
        composition_config = config.get('video_composition', {})
        resolution = tuple(composition_config.get('resolution', [1920, 1080]))
        fps = composition_config.get('fps', 30)

        # 从全局配置读取 debug 状态，用于控制 FFmpeg 日志的详细程度
        # silent 的值与 debug 的值相反 (debug: true -> silent: false)
        is_debug_mode = config.get('debug', False)

        composer = FrameAccurateVideoComposer(
            task_id=self.task_manager.task_id,
            video_struct_path=assets_scenes_path,
            input_audio_path=audio_path,
            output_video_path=output_path,
            temp_dir=temp_dir,
            resolution=resolution,
            fps=fps,
            silent=not is_debug_mode
        )
        
        composer.execute()
        
        log.success(f"Frame-accurate composition complete. Base video at: {output_path}")
        return output_path

    def run(self, stage: str, burn_subtitle: bool):
        """
        Step 2: Runs the final video assembly.
        The 'stage' parameter is ignored as the logic is now unified.
        """
        log.info(f"--- Starting Final Assembly for Task ID: {self.task_manager.task_id} (Burn Subtitle: {burn_subtitle}) ---")

        # 1. 始终调用新引擎生成带音频的基准视频 (video_with_audio.mp4)
        video_with_audio_path = self._run_frame_accurate_composition()

        # 2. 根据 burn_subtitle 参数决定最终产物
        if burn_subtitle:
            log.info("Proceeding to burn subtitles...")

            # 调用旧 composer 仅用于烧录字幕，生成 video_with_subtitles.mp4
            subtitled_video_path = self.core_composer.burn_subtitles_to_video(video_with_audio_path)

            # 将带字幕的视频复制为最终产物 final_video.mp4
            shutil.copy(subtitled_video_path, self.final_video_path)
            log.success(f"Video with subtitles created and copied to {self.final_video_path}")
        else:
            # 如果不烧录字幕，直接将带音频的视频复制为最终产物 final_video.mp4
            shutil.copy(video_with_audio_path, self.final_video_path)
            log.success(f"Video with audio copied to {self.final_video_path}")

        return self.final_video_path
