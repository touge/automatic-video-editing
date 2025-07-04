import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status, BackgroundTasks, Form
from fastapi.responses import FileResponse, JSONResponse
from typing import Annotated

# 根据 README.md 中的启动说明 (从项目根目录运行 uvicorn)，Python 会自动将根目录加入 sys.path。
# 因此，不再需要手动修改路径。

from api.auth import verify_api_key
from api.utils import save_upload_file, run_stage_1_and_get_task_id, composition_task_wrapper
from src.utils import get_task_path

router = APIRouter()

@router.post("/v1/analysis",
             summary="阶段一：分析字幕",
             dependencies=[Depends(verify_api_key)])
async def create_analysis_task(subtitles: UploadFile = File(..., description="SRT字幕文件")):
    """
    上传一个SRT字幕文件，启动分析流程。
    该流程会进行场景分割和关键词提取，并返回一个任务ID。
    """
    if not subtitles.filename.endswith('.srt'):
        raise HTTPException(status_code=400, detail="无效的文件类型，请上传SRT文件。")

    srt_path = save_upload_file(subtitles)
    
    try:
        task_id = run_stage_1_and_get_task_id(srt_path)
        return {"task_id": task_id, "message": "分析任务创建成功。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析过程中发生错误: {str(e)}")
    finally:
        # 清理上传的临时文件
        if os.path.exists(srt_path):
            os.remove(srt_path)

@router.post("/v1/composition",
             summary="阶段二：合成视频 (后台任务)",
             dependencies=[Depends(verify_api_key)])
async def create_composition_task(
    background_tasks: BackgroundTasks,
    task_id: Annotated[str, Form(description="阶段一返回的任务ID")],
    audio: UploadFile = File(..., description="配音的音频文件 (如 .mp3, .wav)"),
    subtitles: UploadFile | None = File(None, description="可选的SRT字幕文件，用于烧录到视频中")
):
    """
    提供任务ID、音频文件和可选的字幕文件，启动视频合成流程。
    这是一个后台任务，会立即返回，视频将在后台生成。
    """
    audio_path = save_upload_file(audio)
    subtitle_path = save_upload_file(subtitles) if subtitles else None
    
    # 将耗时的合成任务添加到后台
    # wrapper函数负责在任务结束后清理上传的临时文件
    background_tasks.add_task(composition_task_wrapper, task_id, audio_path, subtitle_path)

    return {"message": "视频合成任务已在后台启动。", "task_id": task_id}

@router.get("/v1/status/{task_id}",
            summary="查询任务状态",
            dependencies=[Depends(verify_api_key)])
async def get_task_status(task_id: str):
    """
    根据任务ID查询视频合成的状态。
    """
    task_path = get_task_path(task_id)
    final_video_path = os.path.join(task_path, "final_video.mp4")
    
    if not os.path.exists(task_path):
        raise HTTPException(status_code=404, detail="任务ID不存在。")

    if os.path.exists(final_video_path):
        return {"task_id": task_id, "status": "COMPLETED", "detail": "视频合成已完成。"}
    else:
        # 更复杂的状体判断可以检查日志文件等
        return {"task_id": task_id, "status": "PENDING_OR_IN_PROGRESS", "detail": "视频正在合成中或等待合成。"}

@router.get("/v1/download/{task_id}",
            summary="下载最终视频",
            dependencies=[Depends(verify_api_key)])
async def download_video(task_id: str):
    """
    根据任务ID下载已合成的最终视频。
    """
    task_path = get_task_path(task_id)
    final_video_path = os.path.join(task_path, "final_video.mp4")

    if not os.path.exists(final_video_path):
        return JSONResponse(
            status_code=404,
            content={"message": "视频文件未找到。请先通过 /v1/status/{task_id} 确认任务已完成。"}
        )
    
    return FileResponse(path=final_video_path, media_type='video/mp4', filename=f"{task_id}_final_video.mp4")
