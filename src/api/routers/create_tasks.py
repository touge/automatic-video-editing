import os
import sys
import base64
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Body, Request
from typing import Optional, Literal, Dict, Any # Keep Dict, Any for create_task return type
from pydantic import BaseModel
from pathlib import Path

from src.core.task_manager import TaskManager
from src.api.security import verify_token
from src.logger import log
from src.config_loader import config

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks & Status - Task Creation and Status"],
    dependencies=[Depends(verify_token)]
)

# 允许的文件后缀
ALLOWED_EXTENSIONS = {".txt", ".md", ".docx"}

@router.post("", summary="Create and initialize a task")
async def create_task(
    task_id: Optional[str] = Form("", description="Optional task ID to overwrite or continue an existing task."),
    file: UploadFile = File(..., description="The script file (.txt) for the video."),
    speaker: Optional[str] = Form("", description="The speaker for TTS."),
    video_style: Optional[str] = Form("", description="The style of the video, e.g., 'science', 'health'.")
):
    """
    Creates a new task or uses an existing one, and uploads the script file.

    - **task_id**: (Optional) Provide an existing task ID to overwrite its script.
                   If left empty, a new task ID will be generated automatically.
    - **file**: (Required) A text document to be used as the video script.
    """
    # if not file.filename.endswith('.txt'):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .txt file.")

    try:
        task_manager = TaskManager(task_id)
        script_content_bytes = await file.read()
        saved_path = task_manager.save_script(script_content_bytes)
        log.info(f"Script for task '{task_manager.task_id}' saved to '{saved_path}'")

        step_name = "task_creation"
        if task_manager.is_new:
            message = f"New task '{task_manager.task_id}' created successfully and script uploaded."
        else:
            message = f"Existing task '{task_manager.task_id}' updated with new script."
        
        # Task creation/update is an atomic operation, so its status is SUCCESS upon completion.
        # 确定 speaker 和 video_style, 如果未提供则使用默认值
        final_speaker = speaker
        if not final_speaker:
            tts_config = config.get('tts_providers', {})
            provider_name = tts_config.get('use')
            provider_config = tts_config.get(provider_name, {})
            speakers = provider_config.get('speakers', {})
            final_speaker = speakers.get('default')
            log.info(f"未提供speaker，使用提供商 '{provider_name}' 的默认值: '{final_speaker}'")

        final_video_style = video_style
        if not final_video_style:
            # 如果未提供video_style，则将其设置为字符串 "default"
            # 下游模块（如SceneGenerator）将负责使用这个key来从配置中查找实际的prompt文件路径
            final_video_style = "default"
            log.info(f"未提供video_style，使用默认键名: '{final_video_style}'")

        details = {
            "message": message,
            "script_path": saved_path,
            "speaker": final_speaker,
            "video_style": final_video_style
        }

        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
            details=details
        )

        return {
            "task_id": task_manager.task_id,
            "message": message,
            "status": TaskManager.STATUS_SUCCESS,
            "step": step_name
        }
    except Exception as e:
        log.error(f"Failed to create task or save script: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")

@router.get("/{task_id}/status", summary="Query the status of a specific task")
async def get_task_status(task_id: str):
    """
    Queries the current status and results of a specific task.
    """
    try:
        task_manager = TaskManager(task_id)
        status_data = task_manager.get_task_status()
        return status_data
    except Exception as e:
        log.error(f"Failed to retrieve status for task '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
