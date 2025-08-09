import os
import sys
import base64
from fastapi import APIRouter, HTTPException, Depends, Body, Request, BackgroundTasks
from typing import Optional, Dict, Any
from pydantic import BaseModel
import httpx
from starlette.concurrency import run_in_threadpool  # 用于线程池执行阻塞操作

from src.core.task_manager import TaskManager
from src.logic.subtitle_generator import SubtitleGenerator
from src.api.security import verify_token
from src.logger import log
from src.utils import get_relative_url

# 添加项目根路径，保证模块能正确导入
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 路由定义：任务模块，自动带 Token 鉴权
router = APIRouter(
    prefix="/tasks",
    # tags=["Audio & Subtitles - Audio and Subtitles"],
    tags=["音频和字幕 - Audio and Subtitles"],
    dependencies=[Depends(verify_token)]
)

class SubtitleRequest(BaseModel):
    """
    JSON structure for subtitle generation request.
    Optional fields: audio_url, audio_base64, or audio_file_bytes.
    """
    audio_url: Optional[str] = ""
    audio_base64: Optional[str] = ""
    audio_file_bytes: Optional[bytes] = b""

async def _generate_subtitles_task(task_id: str, audio_input_data: Dict[str, Any], request: Request):
    """Background task for generating subtitles."""
    task_manager = TaskManager(task_id)
    step_name = "subtitle_generation"
    try:
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step=step_name,
            details={"message": "Subtitle generation task has started."}
        )

        script_path = task_manager.get_file_path('original_doc')
        preprocessor = SubtitleGenerator(task_id=task_id, doc_file=script_path)

        audio_content = None
        if audio_input_data.get("audio_url"):
            log.info(f"Task '{task_id}': Downloading audio from URL...")
            async with httpx.AsyncClient() as client:
                response = await client.get(audio_input_data["audio_url"], follow_redirects=True)
                response.raise_for_status()
                audio_content = response.content
        elif audio_input_data.get("audio_base64"):
            log.info(f"Task '{task_id}': Decoding Base64 audio...")
            audio_content = audio_input_data["audio_base64"]

        if audio_content:
            await run_in_threadpool(preprocessor.save_final_audio, audio_content)

        srt_path = await run_in_threadpool(preprocessor.run)
        srt_url = get_relative_url(srt_path, request)

        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
            details={
                "message": "Subtitle generation completed successfully.",
                "srt_url": srt_url,
                "final_srt_path": srt_path
            }
        )
        log.success(f"Subtitle generation task '{task_id}' completed successfully.")
    except Exception as e:
        error_message = f"Subtitle generation failed: {str(e)}"
        log.error(f"Background subtitle generation task '{task_id}' failed: {error_message}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": error_message}
        )


@router.post("/{task_id}/subtitles", summary="为任务生成字幕/Generate subtitles for a task (task_id in path + JSON body)")
async def generate_subtitles(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    payload: SubtitleRequest = Body(...)
):
    try:
        task_manager = TaskManager(task_id)
        step_name = "subtitle_generation"
        
        script_path = task_manager.get_file_path('original_doc')
        if not os.path.exists(script_path):
            raise HTTPException(status_code=404, detail=f"Script file for task '{task_id}' not found.")

        audio_input_data = {}
        if payload.audio_file_bytes:
            audio_input_data["audio_file"] = payload.audio_file_bytes
        elif payload.audio_url:
            audio_input_data["audio_url"] = payload.audio_url
        elif payload.audio_base64:
            audio_input_data["audio_base64"] = payload.audio_base64

        background_tasks.add_task(_generate_subtitles_task, task_id, audio_input_data, request)
        
        message = "Subtitle generation task submitted successfully. Awaiting processing."
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
    except Exception as e:
        log.error(f"Task '{task_id}' submission failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
