from fastapi import APIRouter, UploadFile, File, Security, HTTPException, status
import os

from api.auth import verify_api_key
from api.utils import run_stage_1_and_get_task_id
from api.utils import save_upload_file

router = APIRouter(tags=["Analysis"])

@router.post(
    "/v1/analysis",
    summary="阶段一：分析字幕",
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
        400: {"description": "Bad Request"},
        500: {"description": "Internal Server Error"}
    },
)
async def create_analysis_task(
    subtitles: UploadFile = File(..., description="SRT 字幕文件"),
    api_key: str        = Security(verify_api_key),
):
    if not subtitles.filename.endswith(".srt"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请上传有效的 SRT 文件")
    
    path = save_upload_file(subtitles)
    try:
        task_id = run_stage_1_and_get_task_id(path)
        return {"task_id": task_id, "message": "分析任务创建成功"}
    finally:
        if os.path.exists(path):
            os.remove(path)
