import os
from typing import List, Dict, Any
from src.core.task_manager import TaskManager
from src.core.video_compositor import VideoCompositor
from src.logger import log

class DigitalHumanCompositor:
    # 文件描述：此类是一个高级服务，负责编排数字人视频合成任务。
    # 它从任务状态文件中获取素材路径，准备合成参数，然后调用底层的 VideoCompositor 来执行实际的视频处理。
    
    def __init__(self, task_id: str):
        """
        构造函数：初始化 DigitalHumanCompositor 实例。

        Args:
            task_id (str): 当前任务的唯一标识符。
        Raises:
            ValueError: 如果 task_id 为空。
        """
        # 确保 task_id 不能为空，这是任务的唯一标识
        if not task_id:
            raise ValueError("A task_id must be provided.")
        # 初始化任务管理器，用于访问任务的状态文件和路径
        self.task_manager = TaskManager(task_id)
        # 初始化底层的视频合成器，它将处理 FFmpeg 相关的具体操作
        self.compositor = VideoCompositor()

    def run(self, composition_specs: List[Dict[str, Any]], output_filename: str,
            main_clip_params: Dict = None, base_video_volume: float = 1.0):
        """
        执行数字人视频合成任务。

        Args:
            composition_specs (List[Dict[str, Any]]): 描述要叠加的短视频片段的参数列表。
            output_filename (str): 最终合成视频的输出文件名。
            main_clip_params (Dict, optional): 主视频的裁剪参数。默认为 None。
            base_video_volume (float, optional): 主视频的音量。默认为 1.0。

        Returns:
            str: 最终合成视频的完整文件路径。
        Raises:
            FileNotFoundError: 如果基础视频文件不存在。
            ValueError: 如果合成参数与视频片段数量不匹配。
        """
        
        # 记录日志，表示合成任务已开始
        log.info(f"--- Starting Digital Human Composition for Task ID: {self.task_manager.task_id} ---")

        # 1. 从 status.json 获取正确的路径
        log.info("Fetching paths from status.json...")
        status_data = self.task_manager.get_task_status()
        
        # 基础视频是主视频
        base_video_path = status_data.get("final_video_path")
        
        # 待合成的视频是经过绿幕处理的数字人切片
        digital_human_data = status_data.get("digital_human", {})
        if not digital_human_data:
            raise ValueError("'digital_human' data not found in status file.")
        
        segment_paths = digital_human_data.get("processed_segment_videos", {}).get("paths", [])
        if not segment_paths:
            log.warning("Processed segments not found, falling back to raw segments.")
            segment_paths = digital_human_data.get("segment_videos", {}).get("paths", [])
        
        log.info(f"Base video path: {base_video_path}")
        log.info(f"Found {len(segment_paths)} segment paths.")

        # 验证基础视频路径是否存在
        if not base_video_path or not os.path.exists(base_video_path):
            raise FileNotFoundError(f"Base video not found for task {self.task_manager.task_id}")
        
        # 验证短视频片段路径列表与传入的合成参数列表是否匹配
        if not segment_paths or len(segment_paths) != len(composition_specs):
            raise ValueError("Mismatch between provided composition specs and available video segments.")

        # 2. 组合路径和合成指令
        short_videos_to_composite = []
        # 遍历传入的合成参数，并将对应的文件路径添加到每个参数字典中
        for i, spec in enumerate(composition_specs):
            spec['path'] = segment_paths[i]
            short_videos_to_composite.append(spec)

        # 3. 定义输出路径
        # 拼接任务目录和输出文件名，生成最终的完整输出路径
        output_path = os.path.join(self.task_manager.task_path, output_filename)

        # 4. 调用核心合成器并进行严格的错误检查
        success = self.compositor.composite_videos(
            base_video_path=base_video_path,
            short_videos=short_videos_to_composite,
            output_path=output_path,
            clip_params=main_clip_params,
            base_volume=base_video_volume
        )

        # 如果合成失败，则立即抛出异常
        if not success:
            raise Exception("The core video compositor failed to execute the FFmpeg command.")

        # 5. 更新任务状态 (可选，但推荐)
        # 记录成功日志，并返回最终视频路径
        log.success(f"Digital human composition complete. Final video at: {output_path}")
        return output_path
