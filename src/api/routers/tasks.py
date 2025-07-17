import os
import sys
import base64
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Body, Request
from typing import Optional, Literal
from pydantic import BaseModel

from src.core.task_manager import TaskManager
from src.logic.audio_preprocessor import AudioPreprocessor
from src.api.security import verify_token
from src.logger import log

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks - 任务管理与处理"],
    dependencies=[Depends(verify_token)]
)

class TtsParams(BaseModel):
    speaker: Optional[str] = None
    speed: Optional[float] = None
    response_format: Literal["url", "base64", "binary"] = "url"

@router.post("", summary="创建并初始化一个任务")
async def create_task(
    task_id: Optional[str] = Form(None, description="可选的任务ID，用于覆盖或继续现有任务。"),
    file: UploadFile = File(..., description="用于视频的脚本文件 (.txt)。")
):
    """
    创建一个新任务或使用现有任务，并上传脚本文件。

    - **task_id**: (可选) 提供一个已存在的任务ID来覆盖该任务的脚本。
                   如果留空，系统将自动生成一个新的任务ID。
    - **file**: (必需) 作为视频脚本的文本文档。
    """
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .txt file.")

    try:
        task_manager = TaskManager(task_id)
        script_content_bytes = await file.read()
        saved_path = task_manager.save_script(script_content_bytes)
        log.info(f"Script for task '{task_manager.task_id}' saved to '{saved_path}'")
        message = "New task created and script saved." if task_manager.is_new else "Existing task updated with new script."
        return {
            "task_id": task_manager.task_id,
            "message": message,
            "script_content": script_content_bytes.decode('utf-8')
        }
    except Exception as e:
        log.error(f"Failed to create task or save script: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")

@router.post("/{task_id}/audio", summary="为指定任务生成音频")
async def generate_audio(
    request: Request,
    task_id: str,
    tts_params: TtsParams = Body(TtsParams(), description="可选的TTS参数及响应格式。")
):
    """
    根据任务的脚本，为指定的任务生成音频，并按要求返回结果。
    此操作会合成并合并所有音频片段，生成 final_audio.wav。
    """
    try:
        task_manager = TaskManager(task_id)
        script_path = task_manager.get_file_path('original_doc')
        preprocessor = AudioPreprocessor(task_id=task_id, doc_file=script_path, _from_api=True)
        
        # Convert Pydantic model to dict, excluding None values so defaults in providers are used.
        tts_kwargs = tts_params.dict(exclude_none=True)
        response_format = tts_kwargs.pop("response_format", "url")
        final_audio_path = preprocessor.run_synthesis_only(**tts_kwargs)
        
        if response_format == "binary":
            return FileResponse(path=final_audio_path, media_type="audio/wav", filename="final_audio.wav")
        
        if response_format == "base64":
            with open(final_audio_path, "rb") as audio_file:
                encoded_string = base64.b64encode(audio_file.read()).decode('utf-8')
            return {"task_id": task_id, "status": "success", "format": "base64", "audio_content": encoded_string}

        relative_path = os.path.relpath(final_audio_path, start=project_root)
        url_path = f"static/{relative_path.replace(os.path.sep, '/')}"
        audio_url = f"{str(request.base_url).rstrip('/')}/{url_path}"
        return {"task_id": task_id, "status": "success", "format": "url", "audio_url": audio_url}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task or script for task_id '{task_id}' not found.")
    except Exception as e:
        log.error(f"Failed to generate audio for task '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")

@router.post("/{task_id}/subtitles", summary="为指定任务生成字幕")
async def generate_subtitles(
    request: Request,
    task_id: str,
    audio_file: Optional[UploadFile] = File(None, description="可选的音频文件，将覆盖任务中现有的 final_audio.wav。"),
    audio_url: Optional[str] = Form(None, description="可选的音频文件URL，将下载并覆盖任务中现有的 final_audio.wav。"),
    audio_base64: Optional[str] = Form(None, description="可选的Base64编码的音频数据，将解码并覆盖。")
):
    """
    为指定任务的音频文件生成SRT字幕。

    - **音频输入 (可选)**: 您可以通过三种方式之一提供音频，优先级从高到低为：二进制文件 > URL > Base64。
      如果提供了音频，它将覆盖任务目录中现有的 `final_audio.wav`。
      如果未提供任何音频，此操作将使用任务目录中已存在的 `final_audio.wav`。
    """
    try:
        task_manager = TaskManager(task_id)
        script_path = task_manager.get_file_path('original_doc')
        preprocessor = AudioPreprocessor(task_id=task_id, doc_file=script_path, _from_api=True)

        audio_content = None
        if audio_file:
            log.info(f"Processing provided audio file for task '{task_id}'.")
            audio_content = await audio_file.read()
        elif audio_url:
            log.info(f"Downloading audio from URL for task '{task_id}'.")
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(audio_url, follow_redirects=True)
                response.raise_for_status()
                audio_content = response.content
        elif audio_base64:
            log.info(f"Decoding Base64 audio for task '{task_id}'.")
            audio_content = base64.b64decode(audio_base64)
        
        if audio_content:
            preprocessor.save_final_audio(audio_content)

        srt_path = preprocessor.run_subtitles_generation()
        
        relative_path = os.path.relpath(srt_path, start=project_root)
        url_path = f"static/{relative_path.replace(os.path.sep, '/')}"
        srt_url = f"{str(request.base_url).rstrip('/')}/{url_path}"
        
        return {"task_id": task_id, "status": "success", "message": "Subtitles generated successfully.", "srt_url": srt_url}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task, script, or final_audio.wav for task_id '{task_id}' not found.")
    except Exception as e:
        log.error(f"Failed to generate subtitles for task '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
