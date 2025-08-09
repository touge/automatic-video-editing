import os
import sys
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config_loader import config
from src.core.task_manager import TaskManager
from src.core.video_compositor import VideoCompositor
from src.api.security import verify_token
from src.logger import log
from starlette.concurrency import run_in_threadpool
from src.utils import get_relative_url, to_slash_path

router = APIRouter(
    prefix="/tasks",
    # tags=["视频处理 - Video Processing"],
    tags=["视频合成 - Video Composition"],
    dependencies=[Depends(verify_token)]
)

async def _process_segments_task(task_id: str, http_request: Request):
    task_manager = TaskManager(task_id)
    step_name = "process_digital_human_segments"
    
    try:
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step=step_name,
            details={"message": "Starting digital human segment processing (chroma key)."}
        )
        
        status = task_manager.get_task_status()
        digital_human_data = status.get("digital_human", {})
        segment_paths = digital_human_data.get("segment_videos", {}).get("paths", [])

        if not segment_paths:
            raise ValueError("No video segments found to process.")

        processed_dir = os.path.join(task_manager.task_path, ".videos", "digital_human", "processed_segments")
        os.makedirs(processed_dir, exist_ok=True)

        compositor = VideoCompositor()
        processed_paths = []
        processed_urls = []

        # 从配置中获取背景图片路径
        background_path = config.get("composition_settings", {}).get("video_background")
        if not background_path or not os.path.exists(background_path):
            raise ValueError(f"Background image not found at path: {background_path}")

        for segment_path in segment_paths:
            base_filename, _ = os.path.splitext(os.path.basename(segment_path))
            output_filename = f"{base_filename}.mp4" # 输出仍为 mp4
            output_path = os.path.join(processed_dir, output_filename)
            
            success = await run_in_threadpool(
                compositor.process_short_video,
                input_path=segment_path,
                output_path=output_path,
                background_path=background_path
            )

            if not success:
                raise Exception(f"Failed to process segment: {segment_path}")

            processed_paths.append(output_path)
            processed_urls.append(get_relative_url(output_path, http_request))

        # 修正：合并而不是覆盖 digital_human 数据，并确保路径使用正斜杠
        current_digital_human_data = status.get("digital_human", {})
        current_digital_human_data["processed_segment_videos"] = {
            "paths": [to_slash_path(p) for p in processed_paths],
            "urls": processed_urls
        }

        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
            details={
                "digital_human": current_digital_human_data
            }
        )
        log.success(f"Chroma key processing completed for task '{task_id}'.")

    except Exception as e:
        error_message = f"Failed to process video segments: {str(e)}"
        log.error(f"Task '{task_id}' failed during segment processing: {error_message}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": error_message}
        )

@router.post("/{task_id}/process-digital-human-segments", summary="处理数字人片段/Process digital human segments (apply chroma key)")
async def process_digital_human_segments(task_id: str, background_tasks: BackgroundTasks, http_request: Request):
    task_manager = TaskManager(task_id)
    status = task_manager.get_task_status()
    if not status.get("digital_human", {}).get("segment_videos"):
        raise HTTPException(status_code=404, detail="Raw digital human segments not found.")

    background_tasks.add_task(_process_segments_task, task_id, http_request)
    
    return {"task_id": task_id, "status": "SUBMITTED", "message": "Digital human segment processing task submitted."}
