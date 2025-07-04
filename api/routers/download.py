import os
from fastapi import APIRouter, Security
from fastapi.responses import FileResponse, JSONResponse

from api.auth import verify_api_key
from src.utils import get_task_path

router = APIRouter(tags=["Download"])

@router.get(
    "/v1/download/{task_id}",
    summary="下载最终视频",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}, 404: {"description": "Not Found"}}
)
async def download_video(
    task_id: str,
    api_key: str = Security(verify_api_key),
):
    task_dir = get_task_path(task_id)
    video_fp = os.path.join(task_dir, "final_video.mp4")
    
    if not os.path.exists(video_fp):
        return JSONResponse(
            status_code=404,
            content={"message": "视频未找到或尚未生成完成"}
        )
    return FileResponse(video_fp, media_type="video/mp4", filename=f"{task_id}.mp4")
