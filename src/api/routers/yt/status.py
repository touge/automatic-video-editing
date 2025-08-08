from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from src.api.security import verify_token
from src.core.task_manager import TaskManager  # 导入核心 TaskManager

router = APIRouter()

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    step: Optional[str] = None
    timestamp: Optional[str] = None
    task_name: Optional[str] = None


@router.get("/status/{task_id}", response_model=TaskStatusResponse, dependencies=[Depends(verify_token)])
async def get_task_status(task_id: str):
    """
    查询指定任务ID的当前状态和结果。
    """
    task_manager = TaskManager(task_id=task_id)
    
    # 检查状态文件是否存在，如果不存在，说明任务从未被创建
    status_file = task_manager._get_status_file_path()
    if not status_file.exists():
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    # 从文件加载最新状态
    task_info = task_manager.get_task_status()
    
    return TaskStatusResponse(**task_info)
