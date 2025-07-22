import os
import sys
import base64
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Body, Request, BackgroundTasks
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel
from starlette.responses import FileResponse
import httpx
from starlette.concurrency import run_in_threadpool # Import run_in_threadpool

from src.core.task_manager import TaskManager
from src.logic.audio_generator import AudioGenerator
from src.api.security import verify_token
from src.logger import log
from src.utils import get_relative_url

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

router = APIRouter(
    prefix="/tasks",
    tags=["Audio & Subtitles - Audio and Subtitles"],
    dependencies=[Depends(verify_token)]
)

async def _generate_audio_task(task_id: str, request: Request):
    """Background task: Generate audio and initial scenes from the script."""
    task_manager = TaskManager(task_id)
    try:
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step="audio_generation",
            details={"message": "Audio generation task has started."}
        )
        
        script_path = task_manager.get_file_path('original_doc')
        preprocessor = AudioGenerator(task_id=task_id, doc_file=script_path)
        
        await run_in_threadpool(preprocessor.run)
        
        final_audio_path = task_manager.get_file_path('final_audio')
        audio_url = get_relative_url(final_audio_path, request)
        
        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step="audio_generation",
            details={
                "message": "Audio generation and initial scene processing completed successfully.",
                "audio_url": audio_url,
                "final_audio_path": final_audio_path
            }
        )
        log.success(f"Audio generation task '{task_id}' completed successfully.")
    except Exception as e:
        error_message = f"Audio generation failed: {str(e)}"
        log.error(f"Background audio generation task '{task_id}' failed: {error_message}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step="audio_generation",
            details={"message": error_message}
        )

@router.post("/{task_id}/audio", summary="Generate audio and scenes from script (Async)")
async def generate_audio(task_id: str, background_tasks: BackgroundTasks, request: Request):
    try:
        task_manager = TaskManager(task_id)
        script_path = task_manager.get_file_path('original_doc')
        if not os.path.exists(script_path):
            raise HTTPException(status_code=404, detail=f"Script for task_id '{task_id}' not found. Please create the task first.")

        background_tasks.add_task(_generate_audio_task, task_id, request)
        
        message = "Audio generation task submitted successfully. Awaiting processing."
        task_manager.update_task_status(
            TaskManager.STATUS_PENDING,
            step="audio_generation",
            details={"message": message}
        )
        
        return {
            "task_id": task_id,
            "status": TaskManager.STATUS_PENDING,
            "message": message
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task or script for task_id '{task_id}' not found.")
    except Exception as e:
        log.error(f"Failed to submit audio generation task for '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
