import os
import sys
from fastapi import APIRouter, Depends, HTTPException, Body, BackgroundTasks
from pydantic import BaseModel
from typing import Literal

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.core.task_manager import TaskManager
from src.logic.video_generator import VideoGenerator
from src.api.security import verify_token
from src.logger import log
from starlette.concurrency import run_in_threadpool
from src.utils import get_relative_url
from fastapi import Request

router = APIRouter(
    prefix="/tasks",
    tags=["Composition Steps - Video Composition"],
    dependencies=[Depends(verify_token)]
)

async def _assemble_video_task(task_id: str, burn_subtitle: bool, request: Request):
    """Background task: Assemble the final video."""
    task_manager = TaskManager(task_id)
    step_name = "video_assembly"
    try:
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step=step_name,
            details={"message": f"Final video assembly task has started (burn subtitles: {burn_subtitle})."}
        )
        
        preprocessor = VideoGenerator(task_id)
        final_video_path = await run_in_threadpool(preprocessor.run, stage="full", burn_subtitle=burn_subtitle)
        
        video_url = get_relative_url(final_video_path, request)

        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
            details={
                "message": "Final video assembly completed successfully.",
                "video_url": video_url,
                "final_video_path": final_video_path
            }
        )
        log.success(f"Final video assembly task '{task_id}' completed successfully.")
    except Exception as e:
        error_message = f"Final video assembly failed: {str(e)}"
        log.error(f"Background final video assembly task '{task_id}' failed: {error_message}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": error_message}
        )

@router.post("/{task_id}/assemble", summary="Assemble the final video (Async)")
async def assemble_video(task_id: str, background_tasks: BackgroundTasks, request: Request, burn_subtitle: bool = Body(False, embed=True)):
    """
    **Step 2**: Performs the final video assembly.
    
    This endpoint calls the frame-accurate composition engine to generate the final video with audio.
    You can choose whether to burn subtitles based on the `burn_subtitle` parameter.

    - **Input**: `final_scenes_assets.json` and `final_audio.wav`
    - **Output**: The final video file `final_video.mp4`.
    """
    task_manager = TaskManager(task_id)
    step_name = "video_assembly"

    assets_path = task_manager.get_file_path('final_scenes_with_assets')
    audio_path = task_manager.get_file_path('final_audio')
    if not os.path.exists(assets_path) or not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail=f"Prerequisite file 'final_scenes_assets.json' or 'final_audio.wav' not found for task '{task_id}'. Cannot start video assembly.")

    background_tasks.add_task(_assemble_video_task, task_id, burn_subtitle, request)
    
    message = f"Final video assembly task submitted successfully. Awaiting processing (burn subtitles: {burn_subtitle})."
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
