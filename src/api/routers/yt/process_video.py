import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from src.config_loader import config
from src.core.subtitles_processor import SubtitlesProcessor
from src.utils import get_relative_url
from src.api.security import verify_token
from .utils import parse_srt_file, get_youtube_url, get_video_id
from src.api.routers.yt.simple_task_manager import SimpleTaskManager
from src.api.routers.yt.shared_data import tasks, save_task_status # 导入共享的 tasks 字典和 save_task_status

router = APIRouter()

class ProcessVideoRequest(BaseModel):
    url: str # 接受 video_id 或完整的 URL

async def _process_video_task(task_id: str, video_url: str, request: Request):
    """
    后台任务，执行视频下载和转录。
    """
    tasks[task_id]["status"] = "RUNNING"
    tasks[task_id]["progress"] = 0.0
    save_task_status(task_id) # 保存初始状态
    
    task_manager = SimpleTaskManager(task_id)
    
    # 从 config.yaml 获取缓存目录和 Whisper 模型路径
    base_task_folder = config.get('paths.task_folder', 'tasks')
    
    # 拼接完整的 Whisper 模型路径
    local_models_base_path = config.get('paths.local_models.base_path', 'models')
    whisper_relative_path = config.get('paths.local_models.whisper', 'whisper/faster-whisper-large-v2')
    actual_model_dir = str(Path(local_models_base_path) / Path(whisper_relative_path))

    # 获取代理设置
    proxy_settings = config.get('proxy_settings', {})
    proxy_enabled = proxy_settings.get('enabled', False)
    proxy_address = proxy_settings.get('address', None)
    
    # 根据配置决定是否使用代理
    proxy_to_use = proxy_address if proxy_enabled else None

    # 为当前任务创建缓存目录 (task_id 已包含 'yt-' 前缀)
    task_output_dir = Path(f"{base_task_folder}/{task_id}")
    os.makedirs(task_output_dir, exist_ok=True)
    
    # 根据 video_url 构建完整的 YouTube URL
    youtube_url = get_youtube_url(video_url)
    processor = SubtitlesProcessor(url=youtube_url, proxy=proxy_to_use)
    
    try:
        final_srt_path = task_manager.get_file_path('final_srt')
        
        # 核心逻辑：确保 final_srt_path 文件最终存在
        if not os.path.exists(final_srt_path):
            tasks[task_id]["progress"] = 0.1
            target_filename_base = Path(final_srt_path).stem
            
            # 1. 尝试从平台下载字幕
            downloaded_path = await run_in_threadpool(
                processor.download_platform_subtitles,
                output_dir=str(task_output_dir),
                target_filename_base=target_filename_base
            )

            # 2. 如果平台字幕下载失败，则进行音频转录
            if not downloaded_path:
                print("ℹ️ 平台字幕下载失败，开始进行音频转录流程。")
                tasks[task_id]["progress"] = 0.2
                audio_filename_base = processor.video_id
                await run_in_threadpool(processor.download_audio, str(task_output_dir), audio_filename_base)
                
                if not processor.audio_path or not Path(processor.audio_path).exists():
                    raise Exception("音频下载失败或文件未找到。")

                tasks[task_id]["progress"] = 0.5
                segments_from_whisper = await run_in_threadpool(processor.transcribe_with_whisper, actual_model_dir)
                
                if not segments_from_whisper:
                    raise Exception("音频转录失败或未返回任何片段。")

                tasks[task_id]["progress"] = 0.8
                processor.export_srt(segments_from_whisper, str(task_output_dir), target_filename_base)
        
        # --- 后续处理流程 ---
        # 到这里，final_srt_path 必须存在
        if not os.path.exists(final_srt_path):
            raise Exception(f"SRT 文件生成失败，路径不存在: {final_srt_path}")

        print(f"✅ SRT 文件准备就绪: {final_srt_path}。开始后续处理。")
        
        # 解析 SRT 文件获取 segments
        segments = parse_srt_file(final_srt_path)
        if not segments:
            raise Exception(f"解析 SRT 文件失败或文件为空: {final_srt_path}")

        # 从 segments 中提取纯文本
        full_text = "\n".join([seg.text for seg in segments])

        # 写入 manuscript.txt 文件
        manuscript_path = task_manager.get_file_path('manuscript')
        with open(manuscript_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        
        # 生成 manuscript.txt 的下载链接
        manuscript_url = get_relative_url(manuscript_path, request)
        final_srt_url = get_relative_url(final_srt_path, request)
        tasks[task_id]["progress"] = 1.0

        # 格式化 segments 以便返回
        formatted_segments = [
            {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
            for seg in segments
        ]

        tasks[task_id]["result"] = {
            "video_id": processor.video_id,
            "srt_url": final_srt_url,
            # "full_text": full_text,
            "manuscript_url": manuscript_url,
            # "segments": formatted_segments
        }
        tasks[task_id]["status"] = "COMPLETED"
        tasks[task_id]["progress"] = 1.0
        save_task_status(task_id) # 保存完成状态

        print(f"✅Get subtitles/text from youtube by an ID/url Task completed")

    except Exception as e:
        tasks[task_id]["status"] = "FAILED"
        tasks[task_id]["error"] = str(e)
        tasks[task_id]["progress"] = 1.0
        save_task_status(task_id) # 保存失败状态
    # finally:
    #     # 清理音频文件，保留字幕文件
    #     if processor.audio_path and Path(processor.audio_path).exists():
    #         try:
    #             os.remove(processor.audio_path)
    #             print(f"Cleaned up audio file: {processor.audio_path}")
    #         except Exception as e:
    #             print(f"Error cleaning up audio file {processor.audio_path}: {e}")

from src.api.routers.yt.status import TaskStatusResponse # 导入 TaskStatusResponse

@router.post("/process_video", response_model=TaskStatusResponse, dependencies=[Depends(verify_token)])
async def process_video(http_request: Request, request: ProcessVideoRequest, background_tasks: BackgroundTasks):
    """
    提交一个YouTube视频ID或URL，启动异步下载和转录任务。
    """
    # 从输入中提取 video_id
    video_id = get_video_id(request.url)
    
    # 任务ID使用 "yt-" 前缀和 video_id
    task_id = f"yt-{video_id}"

    # 检查任务是否已存在
    if task_id in tasks:
        # 如果任务已存在，直接返回其当前状态
        return TaskStatusResponse(**tasks[task_id]) # 返回 TaskStatusResponse 实例

    tasks[task_id] = {
        "task_id": task_id,
        "task_name": "process_video",
        "status": "PENDING",
        "progress": 0.0,
        "result": None,
        "error": None
    }
    
    background_tasks.add_task(
        _process_video_task, 
        task_id, 
        request.url, # 传递原始的 url
        http_request
    )
    
    return TaskStatusResponse(task_id=task_id, status="PENDING", progress=0.0) # 返回 TaskStatusResponse 实例
