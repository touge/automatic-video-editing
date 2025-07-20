import os
import sys
import base64
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Body, Request
from typing import Optional, Literal, Dict, Any # Keep Dict, Any for create_task return type
from pydantic import BaseModel

from src.core.task_manager import TaskManager
from src.api.security import verify_token
from src.logger import log

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks - 任务管理与处理"],
    dependencies=[Depends(verify_token)]
)

@router.post("", summary="创建并初始化一个任务")
async def create_task(
    task_id: Optional[str] = Form(None, description="可选的任务ID，用于覆盖或继续现有任务。"),
    file: UploadFile = File(..., description="用于视频的脚本文件 (.txt)。")
):
    """
    创建一个新任务或使用现有任务，并上传脚本文件。

    - **task_id**: (可选) 提供一个已存在的任务ID来覆盖该任务的脚本。
                   如果留空，系统将自动生成一个新的任务ID。
    - **file**: (必需) 作为视频脚本的文本文档。
    """
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .txt file.")

    try:
        task_manager = TaskManager(task_id)
        script_content_bytes = await file.read()
        saved_path = task_manager.save_script(script_content_bytes)
        log.info(f"Script for task '{task_manager.task_id}' saved to '{saved_path}'")
        message = "New task created and script saved." if task_manager.is_new else "Existing task updated with new script."
        
        # Initialize task status with a step
        task_manager.update_task_status(TaskManager.STATUS_PENDING, step="task_initialization", details={"message": message})

        return {
            "task_id": task_manager.task_id,
            "message": message,
            "status": TaskManager.STATUS_PENDING,
            "step": "task_initialization"
        }
    except Exception as e:
        log.error(f"Failed to create task or save script: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")

@router.get("/{task_id}/status", summary="查询指定任务的状态")
async def get_task_status(task_id: str):
    """
    查询指定任务的当前状态和结果。
    """
    try:
        task_manager = TaskManager(task_id)
        status_data = task_manager.get_task_status()
        return status_data
    except Exception as e:
        log.error(f"Failed to retrieve status for task '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
