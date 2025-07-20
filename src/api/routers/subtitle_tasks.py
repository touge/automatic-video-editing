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
from src.logic.audio_preprocessor import AudioPreprocessor
from src.api.security import verify_token
from src.logger import log

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks - 字幕生成与处理"], # Updated tag
    dependencies=[Depends(verify_token)]
)

# Helper function to get relative URL path
def _get_relative_url_path(file_path: str) -> str:
    relative_path = os.path.relpath(file_path, start=project_root)
    return f"static/{relative_path.replace(os.path.sep, '/')}"

async def _generate_subtitles_task(task_id: str, audio_input_data: Dict[str, Any], request_base_url: str):
    """Background task for generating subtitles."""
    task_manager = TaskManager(task_id)
    try:
        task_manager.update_task_status(TaskManager.STATUS_RUNNING, step="subtitle_generation", details={"message": "Subtitle generation in progress."})
        script_path = task_manager.get_file_path('original_doc')
        preprocessor = AudioPreprocessor(task_id=task_id, doc_file=script_path, _from_api=True)

        audio_content = None
        if audio_input_data.get("audio_file"):
            log.info(f"Processing provided audio file for task '{task_id}'.")
            audio_content = audio_input_data["audio_file"]
        elif audio_input_data.get("audio_url"):
            log.info(f"Downloading audio from URL for task '{task_id}'.")
            async with httpx.AsyncClient() as client:
                response = await client.get(audio_input_data["audio_url"], follow_redirects=True)
                response.raise_for_status()
                audio_content = response.content
        elif audio_input_data.get("audio_base64"):
            log.info(f"Decoding Base64 audio for task '{task_id}'.")
            audio_content = base64.b64decode(audio_input_data["audio_base64"])
        
        if audio_content:
            # Save audio content in a thread pool if it's a blocking operation
            await run_in_threadpool(preprocessor.save_final_audio, audio_content)
        
        # Run the blocking operation in a thread pool
        srt_path = await run_in_threadpool(preprocessor.run_subtitles_generation)
        
        srt_url = f"{request_base_url.rstrip('/')}/{_get_relative_url_path(srt_path)}"
        
        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step="subtitle_generation",
            details={"message": "Subtitles generated successfully.", "srt_url": srt_url, "final_srt_path": srt_path}
        )
        log.info(f"Subtitle generation for task '{task_id}' completed successfully.")
    except Exception as e:
        log.error(f"Background subtitle generation for task '{task_id}' failed: {e}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            {"message": f"Subtitle generation failed: {e}", "error": str(e)}
        )

@router.post("/{task_id}/subtitles", summary="为指定任务生成字幕 (异步)")
async def generate_subtitles(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    audio_file: Optional[UploadFile] = File(None, description="可选的音频文件，将覆盖任务中现有的 final_audio.wav。"),
    audio_url: Optional[str] = Form(None, description="可选的音频文件URL，将下载并覆盖任务中现有的 final_audio.wav。"),
    audio_base64: Optional[str] = Form(None, description="可选的Base64编码的音频数据，将解码并覆盖。")
):
    """
    为指定任务的音频文件异步生成SRT字幕。
    客户端应轮询 /tasks/{task_id}/status 接口以获取任务状态和结果。
    """
    try:
        task_manager = TaskManager(task_id)
        script_path = task_manager.get_file_path('original_doc')
        if not os.path.exists(script_path):
            raise HTTPException(status_code=404, detail=f"Script for task_id '{task_id}' not found. Please create task first.")

        audio_input_data = {}
        if audio_file:
            audio_input_data["audio_file"] = await audio_file.read()
        elif audio_url:
            audio_input_data["audio_url"] = audio_url
        elif audio_base64:
            audio_input_data["audio_base64"] = base64.b64decode(audio_base64)

        background_tasks.add_task(_generate_subtitles_task, task_id, audio_input_data, str(request.base_url))
        
        task_manager.update_task_status(TaskManager.STATUS_PENDING, {"message": "Subtitle generation task submitted."})

        return {
            "task_id": task_id,
            "status": TaskManager.STATUS_PENDING,
            "message": "Subtitle generation task submitted. Please poll /tasks/{task_id}/status for updates."
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task, script, or final_audio.wav for task_id '{task_id}' not found.")
    except Exception as e:
        log.error(f"Failed to submit subtitle generation task for '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
