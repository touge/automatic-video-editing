import os
import sys
import base64
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Body, Request, BackgroundTasks
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field
from starlette.responses import FileResponse
import httpx
from starlette.concurrency import run_in_threadpool

from src.core.task_manager import TaskManager
from src.logic.audio_generator import AudioGenerator
from src.api.security import verify_token
from src.logger import log
from src.utils import get_relative_url

#✅ 新增：导入控制器
from src.core.service_controller import ServiceController
service_name = "CosyVoice2"

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

router = APIRouter(
    prefix="/tasks",
    tags=["Audio & Subtitles - Audio and Subtitles"],
    dependencies=[Depends(verify_token)]
)

class AudioGenerationRequest(BaseModel):
    """
    JSON structure for audio generation request. This is currently empty as no payload is required.
    """
    pass

async def _generate_audio_task(task_id: str, step_name: str ,request: Request):
    """Background task: Generate audio and initial scenes from the script."""
    task_manager = TaskManager(task_id)
    # step_name = "audio_generation"

    #######################性能改进，使用ServiceController动态控制第三方服务##################    
    service_controller = ServiceController()  # ✅ 新增：初始化服务控制器
    # ✅ 新增：安全启动服务，阻塞确认关键字
    try:
        # ✅ 新增：使用更可靠的关键字 "Application startup complete."
        service_controller.safe_start(service_name, keyword="Application startup complete.", timeout=60)
    except RuntimeError as e:
        log.error(str(e))
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": str(e)}
        )
        return  # ✅ 中止任务，防止继续执行
    #######################性能改进，使用ServiceController动态控制第三方服务##################

    try:
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step=step_name,
            details={"message": "Audio generation task has started."}
        )
        
        # 从 status.json 获取 speaker
        status_data = task_manager.get_task_status()
        speaker = status_data.get("speaker")
        log.info(f"Retrieved speaker '{speaker}' for task '{task_id}'.")

        script_path = task_manager.get_file_path('original_doc')
        preprocessor = AudioGenerator(task_id=task_id, doc_file=script_path, speaker=speaker)
        
        await run_in_threadpool(preprocessor.run)
        
        final_audio_path = task_manager.get_file_path('final_audio')
        audio_url = get_relative_url(final_audio_path, request)
        
        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
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
            step=step_name,
            details={"message": error_message}
        )
    finally:
        # ✅ 服务关闭
        service_controller.stop(service_name)
        log.info(f"{service_name} service has been stopped.")


@router.post("/{task_id}/audio", summary="Generate audio and scenes from script (Async)")
async def generate_audio(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    payload: AudioGenerationRequest = None # Payload is no longer used but kept for compatibility
):
    try:
        task_manager = TaskManager(task_id)
        step_name = "audio_generation"

        script_path = task_manager.get_file_path('original_doc')
        if not os.path.exists(script_path):
            raise HTTPException(status_code=404, detail=f"Script for task_id '{task_id}' not found. Please create the task first.")

        background_tasks.add_task(_generate_audio_task, task_id=task_id, step_name=step_name, request=request)
        
        message = "Audio generation task submitted successfully. Awaiting processing."
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
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task or script for task_id '{task_id}' not found.")
    except Exception as e:
        log.error(f"Failed to submit audio generation task for '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
