import os
import sys
import base64
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Body, Request, BackgroundTasks
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field
from starlette.responses import FileResponse
import httpx
from starlette.concurrency import run_in_threadpool

from src.core.task_manager import TaskManager
from src.logic.audio_generator import AudioGenerator
from src.api.security import verify_token
from src.logger import log
from src.utils import get_relative_url
from src.config_loader import config
from src.core.service_controller import ServiceController

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

router = APIRouter(
    prefix="/tasks",
    tags=["Audio & Subtitles - Audio and Subtitles"],
    dependencies=[Depends(verify_token)]
)

class AudioGenerationRequest(BaseModel):
    """
    音频生成请求的JSON结构。
    """
    speaker: Optional[str] = Field(None, description="用于TTS的speaker。如果未提供，将使用任务状态中保存的speaker。")

async def _generate_audio_task(task_id: str, step_name: str, speaker: str, request: Request):
    """后台任务：使用一个明确的speaker来从脚本生成音频。"""
    task_manager = TaskManager(task_id)
    service_controller = ServiceController()
    
    tts_config = config.get('tts_providers', {})
    service_to_manage = tts_config.get('use')

    try:
        log.info(f"根据配置，尝试启动服务: {service_to_manage}")
        try:
            service_controller.safe_start(service_to_manage, keyword="Application startup complete.", timeout=300)
        except RuntimeError as e:
            log.error(str(e))
            task_manager.update_task_status(TaskManager.STATUS_FAILED, step=step_name, details={"message": str(e)})
            return
        
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step=step_name,
            details={"message": "音频生成任务已开始。"}
        )
        
        log.info(f"使用最终确定的speaker '{speaker}' 开始生成音频 (任务ID: '{task_id}')。")

        script_path = task_manager.get_file_path('original_doc')
        preprocessor = AudioGenerator(task_id=task_id, doc_file=script_path, speaker=speaker)
        
        await run_in_threadpool(preprocessor.run)
        
        final_audio_path = task_manager.get_file_path('final_audio')
        audio_url = get_relative_url(final_audio_path, request)
        
        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
            details={
                "message": "音频生成和初始场景处理成功完成。",
                "audio_url": audio_url,
                "final_audio_path": final_audio_path
            }
        )
        log.success(f"音频生成任务 '{task_id}' 成功完成。")

    except Exception as e:
        error_message = f"音频生成失败: {str(e)}"
        log.error(f"后台音频生成任务 '{task_id}' 失败: {error_message}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": error_message}
        )
    finally:
        # 确保任务结束时关闭启动的服务
        service_controller.stop(service_to_manage)
        log.info(f"服务 '{service_to_manage}' 已停止。")


@router.post("/{task_id}/audio", summary="从脚本生成音频和场景 (异步)")
async def generate_audio(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: Request, # request is kept for get_relative_url, though it's not used in this function directly
    payload: AudioGenerationRequest = Body(None)
):
    try:
        task_manager = TaskManager(task_id)
        step_name = "audio_generation"

        script_path = task_manager.get_file_path('original_doc')
        if not os.path.exists(script_path):
            raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 的脚本未找到。请先创建任务。")

        # 确定最终要使用的speaker
        final_speaker = None
        # 1. 优先使用请求体中提供的speaker
        if payload and payload.speaker:
            final_speaker = payload.speaker
            log.info(f"使用来自请求体的speaker进行覆盖: '{final_speaker}'")
        else:
            # 2. 否则，直接使用任务状态文件中的speaker (该值在创建任务时已确保存在)
            status_data = task_manager.get_task_status()
            final_speaker = status_data.get("speaker")
            log.info(f"使用来自任务状态文件的speaker: '{final_speaker}'")

        if not final_speaker:
            # 这一步理论上不应该发生，因为create_task保证了speaker的存在。作为安全措施保留。
            raise HTTPException(status_code=500, detail="无法在任务状态中找到speaker，且请求中未提供。")

        # 将确定的speaker传递给后台任务
        background_tasks.add_task(_generate_audio_task, task_id=task_id, step_name=step_name, speaker=final_speaker, request=request)
        
        message = "音频生成任务已成功提交，等待处理。"
        task_manager.update_task_status(
            TaskManager.STATUS_PENDING,
            step=step_name,
            details={"message": message}
        )
        
        return {
            "task_id": task_id,
            "status": TaskManager.STATUS_PENDING,
            "message": message
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Task or script for task_id '{task_id}' not found.")
    except Exception as e:
        log.error(f"Failed to submit audio generation task for '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
