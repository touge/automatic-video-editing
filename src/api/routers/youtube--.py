import asyncio
import os
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends # 导入 Depends
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool # 导入 run_in_threadpool

from src.config_loader import config # 导入 config
from src.core.subtitles_processor import SubtitlesProcessor
from src.api.security import verify_token # 导入验签函数

router = APIRouter()

# 简单的内存任务存储
# 实际生产环境可能需要 Redis, 数据库或其他持久化存储
tasks: Dict[str, Dict[str, Any]] = {}

class ProcessVideoRequest(BaseModel):
    video_id: str = "" # 仅保留 video_id

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str # "PENDING", "RUNNING", "COMPLETED", "FAILED"
    progress: Optional[float] = None # 0.0 to 1.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

async def _process_video_task(task_id: str, video_id: str): # 移除 proxy 和 request_model_dir 参数
    """
    后台任务，执行视频下载和转录。
    """
    tasks[task_id]["status"] = "RUNNING"
    tasks[task_id]["progress"] = 0.0
    
    # 从 config.yaml 获取缓存目录和 Whisper 模型路径
    base_task_folder = config.get('paths.task_folder', 'tasks')
    
    # 拼接完整的 Whisper 模型路径
    local_models_base_path = config.get('paths.local_models.base_path', 'models')
    whisper_relative_path = config.get('paths.local_models.whisper', 'whisper/faster-whisper-large-v2')
    actual_model_dir = str(Path(local_models_base_path) / Path(whisper_relative_path)) # 直接从 config 获取

    # 获取代理设置
    proxy_settings = config.get('proxy_settings', {})
    proxy_enabled = proxy_settings.get('enabled', False)
    proxy_address = proxy_settings.get('address', None)
    
    # 根据配置决定是否使用代理
    proxy_to_use = proxy_address if proxy_enabled else None

    # 为当前任务创建缓存目录 (task_id 已包含 'yt-' 前缀)
    task_output_dir = Path(f"{base_task_folder}/{task_id}")
    os.makedirs(task_output_dir, exist_ok=True)
    
    # 根据 video_id 构建完整的 YouTube URL
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    processor = SubtitlesProcessor(url=youtube_url, proxy=proxy_to_use) # 传递代理设置
    
    try:
        # 1. 下载音频
        tasks[task_id]["progress"] = 0.1
        await run_in_threadpool(processor.download_audio, str(task_output_dir))
        
        if not processor.audio_path or not Path(processor.audio_path).exists():
            raise Exception("Audio download failed or file not found.")

        # 2. 转录音频
        tasks[task_id]["progress"] = 0.5
        segments = await run_in_threadpool(processor.transcribe_with_whisper, actual_model_dir)
        
        if not segments:
            raise Exception("Transcription failed or no segments returned.")

        # 3. 导出 SRT 和纯文本
        tasks[task_id]["progress"] = 0.8
        srt_filename = f"{processor.video_id}_subtitles"
        srt_path = processor.export_srt(segments, str(task_output_dir), srt_filename)
        
        # 从 SRT 文件中提取纯文本
        manuscript_lines = []
        try:
            with open(srt_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line.isdigit() and "-->" not in line and line:
                        manuscript_lines.append(line)
        except Exception as e:
            print(f"Error reading SRT file for text extraction: {e}")
            # 即使提取失败，也继续返回已有的数据
        
        full_text = "\n".join(manuscript_lines)

        # 格式化 segments 以便返回
        formatted_segments = [
            {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
            for seg in segments
        ]

        tasks[task_id]["result"] = {
            "video_id": processor.video_id,
            "srt_path": srt_path,
            "full_text": full_text,
            # "segments": formatted_segments # 确保 segments 也被返回
        }
        tasks[task_id]["status"] = "COMPLETED"
        tasks[task_id]["progress"] = 1.0

    except Exception as e:
        tasks[task_id]["status"] = "FAILED"
        tasks[task_id]["error"] = str(e)
        tasks[task_id]["progress"] = 1.0
    finally:
        # 清理音频文件，保留字幕文件
        if processor.audio_path and Path(processor.audio_path).exists():
            try:
                os.remove(processor.audio_path)
                print(f"Cleaned up audio file: {processor.audio_path}")
            except Exception as e:
                print(f"Error cleaning up audio file {processor.audio_path}: {e}")


@router.post("/process_video", response_model=TaskStatusResponse, dependencies=[Depends(verify_token)]) # 添加验签依赖
async def process_video(request: ProcessVideoRequest, background_tasks: BackgroundTasks):
    """
    提交一个YouTube视频ID，启动异步下载和转录任务。
    """
    # 任务ID使用 "yt-" 前缀和 video_id
    task_id = f"yt-{request.video_id}"

    # 检查任务是否已存在
    if task_id in tasks:
        # 如果任务已存在，直接返回其当前状态
        return TaskStatusResponse(**tasks[task_id])

    tasks[task_id] = {
        "task_id": task_id,
        "status": "PENDING",
        "progress": 0.0,
        "result": None,
        "error": None
    }
    
    background_tasks.add_task(
        _process_video_task, 
        task_id, 
        request.video_id # 仅传递 video_id
    )
    
    return TaskStatusResponse(task_id=task_id, status="PENDING", progress=0.0)

@router.get("/status/{task_id}", response_model=TaskStatusResponse, dependencies=[Depends(verify_token)]) # 添加验签依赖
async def get_task_status(task_id: str):
    """
    查询指定任务ID的当前状态和结果。
    """
    task_info = tasks.get(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskStatusResponse(**task_info)
