import os
import sys
from fastapi import APIRouter, Depends, HTTPException, Body, BackgroundTasks, Request
from pydantic import BaseModel
from typing import Optional
from src.core.task_manager import TaskManager
from src.logic.subtitle_burner import SubtitleBurner
from src.api.security import verify_token
from src.logger import log
from starlette.concurrency import run_in_threadpool
from src.utils import get_relative_url, to_slash_path

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

router = APIRouter(
    prefix="/tasks",
    tags=["字幕压制 - Video burn subtitles into the video [rocessing"],
    dependencies=[Depends(verify_token)]
)

class BurnSubtitleRequest(BaseModel):
    video_path: Optional[str] = ""
    srt_path: Optional[str] = ""

async def _burn_subtitle_task(task_id: str, video_path: str, srt_path: str, output_path: str, request: Request):
    """Background task: Burn subtitles into the video."""
    task_manager = TaskManager(task_id)
    step_name = "subtitle_burn"
    try:
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step=step_name,
            details={"message": "Subtitle burning task has started."}
        )
        
        burner = SubtitleBurner(task_id)
        final_video_path = await run_in_threadpool(burner.burn_subtitles, video_path=video_path, srt_path=srt_path, output_path=output_path)
        video_url = get_relative_url(final_video_path, request)

        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
            details={
                "message": "Subtitle burning completed successfully.",
                "burn_subtitle_video": {
                    "subtitle_video_path": to_slash_path(final_video_path),
                    "subtitle_video_url": video_url
                }
            }
        )
        log.success(f"Subtitle burning task '{task_id}' completed successfully.")
    except Exception as e:
        error_message = f"Subtitle burning failed: {str(e)}"
        log.error(f"Background subtitle burning task '{task_id}' failed: {error_message}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": error_message}
        )

@router.post("/{task_id}/burn_subtitle", summary="烧录字幕到视频/Burn subtitles into video (Async)")
async def burn_subtitle(task_id: str, background_tasks: BackgroundTasks, request: Request, body: BurnSubtitleRequest):
    task_manager = TaskManager(task_id)
    step_name = "subtitle_burn"

    # Determine video path
    if body.video_path:
        video_path = body.video_path
    else:
        status_data = task_manager.get_task_status()
        video_path = status_data.get('composited_video_path')
        if not video_path:
            raise HTTPException(status_code=404, detail=f"'composited_video_path' not found in status file for task '{task_id}'. Please provide a 'video_path'.")

    # Determine SRT path
    srt_path = body.srt_path or task_manager.get_file_path('final_srt')

    # Check for file existence
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"Video file not found at '{video_path}'.")
    if not os.path.exists(srt_path):
        raise HTTPException(status_code=404, detail=f"SRT file not found at '{srt_path}'.")

    # Construct the output path based on the input video path
    task_path = task_manager.get_task_path()
    base_name, ext = os.path.splitext(os.path.basename(video_path))
    output_filename = f"{base_name}_with_srt{ext}"
    output_path = task_path / output_filename

    background_tasks.add_task(_burn_subtitle_task, task_id, video_path, srt_path, str(output_path), request)
    
    message = "Subtitle burning task submitted successfully. Awaiting processing."
    task_manager.update_task_status(
        TaskManager.STATUS_PENDING,
        step=step_name,
        details={"message": message}
    )
    
    return {
        "task_id": task_id,
        "status": TaskManager.STATUS_PENDING,
        "message": message
    }
