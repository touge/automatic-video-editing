import os
from fastapi import APIRouter, Security, HTTPException

from api.auth import verify_api_key
from src.utils import get_task_path

router = APIRouter(tags=["Status"])

@router.get(
    "/v1/status/{task_id}",
    summary="查询任务状态",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}, 404: {"description": "Not Found"}}
)
async def get_task_status(
    task_id: str,
    api_key: str = Security(verify_api_key),
):
    task_dir = get_task_path(task_id)
    if not os.path.isdir(task_dir):
        raise HTTPException(404, "任务ID 不存在")
    
    final_video = os.path.join(task_dir, "final_video.mp4")
    status_str  = "COMPLETED" if os.path.exists(final_video) else "PENDING"
    return {
        "task_id": task_id,
        "status": status_str,
        "detail": "视频已完成" if status_str == "COMPLETED" else "处理中"
    }
