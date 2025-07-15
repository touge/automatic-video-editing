from fastapi import APIRouter, BackgroundTasks, Form, Security, UploadFile, File

from api.auth import verify_api_key
from api.utils import save_upload_file
from api.utils import composition_task_wrapper

router = APIRouter(tags=["Composition"])

@router.post(
    "/v1/composition",
    summary="阶段二：合成视频 (后台任务)",
    responses={401: {"description": "Unauthorized"}, 403: {"description": "Forbidden"}},
)
async def create_composition_task(
    background_tasks: BackgroundTasks,
    task_id: str               = Form(..., description="阶段一返回的任务ID"),
    audio: UploadFile          = File(..., description="配音音频 (.mp3/.wav)"),
    subtitles: UploadFile | None = File(None, description="可选 SRT 字幕"),
    api_key: str               = Security(verify_api_key),
):
    audio_path    = save_upload_file(audio)
    subtitle_path = save_upload_file(subtitles) if subtitles else None

    background_tasks.add_task(
        composition_task_wrapper,
        task_id, audio_path, subtitle_path
    )

    return {"message": "合成任务已启动", "task_id": task_id}
