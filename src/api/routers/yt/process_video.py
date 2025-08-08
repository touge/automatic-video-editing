import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from src.logger import log
from src.config_loader import config
from src.core.subtitles_processor import SubtitlesProcessor
from src.utils import get_relative_url
from src.api.security import verify_token
from .utils import parse_srt_file, get_youtube_url, get_video_id
from src.core.task_manager import TaskManager  # 导入核心 TaskManager

router = APIRouter()

class ProcessVideoRequest(BaseModel):
    url: str # 接受 video_id 或完整的 URL

async def _process_video_task(task_id: str, video_url: str, request: Request):
    """
    后台任务，执行视频下载和转录。
    使用核心 TaskManager 来管理状态和文件路径。
    """
    task_manager = TaskManager(task_id=task_id)
    
    try:
        # 1. 更新状态为运行中
        task_manager.update_task_status(status=TaskManager.STATUS_RUNNING, step="initializing", details={"progress": 0.0})

        # 2. 准备路径和配置
        local_models_base_path = config.get('paths.local_models.base_path', 'models')
        whisper_relative_path = config.get('paths.local_models.whisper', 'whisper/faster-whisper-large-v2')
        actual_model_dir = str(Path(local_models_base_path) / Path(whisper_relative_path))

        proxy_settings = config.get('proxy_settings', {})
        proxy_to_use = proxy_settings.get('address') if proxy_settings.get('enabled') else None

        youtube_url = get_youtube_url(video_url)
        processor = SubtitlesProcessor(url=youtube_url, proxy=proxy_to_use)
        
        final_srt_path = task_manager.get_file_path('final_srt')
        
        # 3. 核心处理逻辑
        if not Path(final_srt_path).exists():
            task_manager.update_task_status(status=TaskManager.STATUS_RUNNING, step="downloading_subtitles", details={"progress": 0.1})
            
            downloaded_path = await run_in_threadpool(
                processor.download_platform_subtitles,
                output_dir=str(task_manager.task_path),
                target_filename_base=Path(final_srt_path).stem
            )

            if not downloaded_path:
                log.info("Platform subtitles not found, starting audio transcription.")
                task_manager.update_task_status(status=TaskManager.STATUS_RUNNING, step="downloading_audio", details={"progress": 0.2})
                
                await run_in_threadpool(processor.download_audio, str(task_manager.task_path), processor.video_id)
                if not processor.audio_path or not Path(processor.audio_path).exists():
                    raise Exception("Audio download failed or file not found.")

                task_manager.update_task_status(status=TaskManager.STATUS_RUNNING, step="transcribing_audio", details={"progress": 0.5})
                segments_from_whisper = await run_in_threadpool(processor.transcribe_with_whisper, actual_model_dir)
                if not segments_from_whisper:
                    raise Exception("Audio transcription failed.")

                task_manager.update_task_status(status=TaskManager.STATUS_RUNNING, step="exporting_srt", details={"progress": 0.8})
                processor.export_srt(segments_from_whisper, str(task_manager.task_path), Path(final_srt_path).stem)
        
        # 4. 后续处理
        if not Path(final_srt_path).exists():
            raise Exception(f"SRT file generation failed, path does not exist: {final_srt_path}")

        log.info(f"SRT file is ready: {final_srt_path}. Starting post-processing.")
        
        segments = parse_srt_file(final_srt_path)
        if not segments:
            raise Exception(f"Failed to parse SRT file or file is empty: {final_srt_path}")

        full_text = "\n".join([seg.text for seg in segments])
        manuscript_path = task_manager.get_file_path('original_doc') # 使用 TaskManager 的标准路径
        with open(manuscript_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        
        # 5. 更新最终状态为成功
        result_details = {
            "progress": 1.0,
            "result": {
                "video_id": processor.video_id,
                "srt_url": get_relative_url(final_srt_path, request),
                "manuscript_url": get_relative_url(manuscript_path, request),
            }
        }
        task_manager.update_task_status(status=TaskManager.STATUS_SUCCESS, step="completed", details=result_details)
        log.success(f"Task '{task_id}' completed successfully.")

    except Exception as e:
        log.error(f"Task '{task_id}' failed: {e}", exc_info=True)
        task_manager.update_task_status(
            status=TaskManager.STATUS_FAILED,
            step="failed_processing",
            details={"progress": 1.0, "error": str(e)}
        )
    finally:
        # 清理临时音频文件
        if processor.audio_path and Path(processor.audio_path).exists():
            try:
                os.remove(processor.audio_path)
                log.info(f"Cleaned up audio file: {processor.audio_path}")
            except Exception as e:
                log.error(f"Error cleaning up audio file {processor.audio_path}: {e}")

from src.api.routers.yt.status import TaskStatusResponse

@router.post("/process_video", response_model=TaskStatusResponse, dependencies=[Depends(verify_token)])
async def process_video(http_request: Request, request: ProcessVideoRequest, background_tasks: BackgroundTasks):
    """
    提交一个YouTube视频ID或URL，启动异步下载和转录任务。
    """
    video_id = get_video_id(request.url)
    task_id = f"yt-{video_id}"
    
    task_manager = TaskManager(task_id=task_id)
    task_info = task_manager.get_task_status()

    # 如果任务已成功或正在运行，直接返回状态
    if task_info["status"] in [TaskManager.STATUS_SUCCESS, TaskManager.STATUS_RUNNING]:
        return TaskStatusResponse(**task_info)

    # 创建新任务或重新启动失败的任务
    task_manager.update_task_status(
        status=TaskManager.STATUS_PENDING,
        step="task_submitted",
        details={
            "task_name": "process_video",
            "progress": 0.0,
            "result": None,
            "error": None
        }
    )
    
    background_tasks.add_task(
        _process_video_task, 
        task_id, 
        request.url,
        http_request
    )
    
    return TaskStatusResponse(task_id=task_id, status=TaskManager.STATUS_PENDING, progress=0.0)
