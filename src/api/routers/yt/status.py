from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from src.api.security import verify_token
from src.api.routers.yt.shared_data import tasks # 导入共享的 tasks 字典

router = APIRouter()

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str # "PENDING", "RUNNING", "COMPLETED", "FAILED"
    progress: Optional[float] = None # 0.0 to 1.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

@router.get("/status/{task_id}", response_model=TaskStatusResponse, dependencies=[Depends(verify_token)])
async def get_task_status(task_id: str):
    """
    查询指定任务ID的当前状态和结果。
    """
    task_info = tasks.get(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskStatusResponse(**task_info)
