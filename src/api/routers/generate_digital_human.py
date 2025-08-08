import os
import sys
import requests
from fastapi import APIRouter, Depends, HTTPException, Form, Request
from typing import Optional, List
from urllib.parse import urlparse

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.core.task_manager import TaskManager
from src.providers.digital_human import get_digital_human_provider, DigitalHumanProvider
from src.core.service_controller import ServiceController
from src.logger import log
from src.api.security import verify_token
from starlette.concurrency import run_in_threadpool
from src.utils import get_relative_url

router = APIRouter(
    prefix="/tasks",
    tags=["视频合成 - Video Composition"],
    dependencies=[Depends(verify_token)]
)

def _download_and_save_file(url: str, save_path: str):
    """下载文件并保存到指定路径"""
    proxies = {"http": None, "https": None}
    with requests.get(url, stream=True, proxies=proxies) as r:
        r.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    log.info(f"Downloaded file from {url} to {save_path}")

@router.post("/{task_id}/digital-human", summary="Generate Digital Human Video (Sync)")
async def generate_digital_human_video(
    request: Request,
    task_id: str,
    character_name: str = Form("44s-医生", description="The name of the character for digital human generation."),
    segments_json: Optional[str] = Form('[{"start":"00:00:00","end":"00:00:45"},{"start":"-00:00:45","end":"-00:00:00"}]', description="A JSON string with segmentation instructions."),
    provider: DigitalHumanProvider = Depends(get_digital_human_provider)
):
    task_manager = TaskManager(task_id)
    service_controller = ServiceController()
    heygem_service_name = "HeygemAPI"
    step_name = "digital_human_generation"

    # 检查任务是否存在
    if not os.path.exists(task_manager.task_path):
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    # 检查音频文件是否已生成并存在
    audio_path = task_manager.get_file_path('final_audio')
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(status_code=400, detail="Final audio file for the task not found. Please run the audio generation step first.")

    try:
        # 更新任务状态，标记数字人视频生成步骤开始
        task_manager.update_task_status(TaskManager.STATUS_RUNNING, step=step_name, details={"message": "Starting digital human video generation."})
        
        # 安全地启动依赖的服务
        log.info(f"Starting service '{heygem_service_name}' for task '{task_id}'.")
        service_controller.safe_start(heygem_service_name, timeout=300)
        
        # 在线程池中运行IO密集型的视频生成任务，避免阻塞主事件循环
        log.info(f"Generating digital human video for task '{task_id}' with character '{character_name}'.")
        result = await run_in_threadpool(
            provider.generate_video,
            audio_file_path=audio_path,
            character_name=character_name,
            segments_json=segments_json
        )
        
        # --- 处理主视频和切片视频 ---
        data = result.get("data", {})
        main_video_url = data.get("url")
        segment_urls = data.get("urls", [])

        if not main_video_url:
            raise ValueError(f"Could not find main video URL in API response. Response: {result}")

        # 定义并创建用于存放数字人视频的目录
        dh_video_dir = os.path.join(task_manager.task_path, ".videos", "digital_human")
        os.makedirs(dh_video_dir, exist_ok=True)

        # 下载主视频
        main_video_filename = os.path.basename(urlparse(main_video_url).path)
        main_video_local_path = os.path.join(dh_video_dir, main_video_filename)
        await run_in_threadpool(_download_and_save_file, main_video_url, main_video_local_path)
        
        # 更新响应中的主视频URL为可访问的本地URL
        main_video_relative_url = get_relative_url(main_video_local_path, request)
        result["data"]["url"] = main_video_relative_url
        
        local_segment_urls = []
        local_segment_paths = [] # 新增：用于存储本地路径
        if segment_urls:
            log.info(f"Found {len(segment_urls)} video segments. Downloading...")
            dh_segment_dir = os.path.join(dh_video_dir, "segments")
            os.makedirs(dh_segment_dir, exist_ok=True)
            
            for i, seg_url in enumerate(segment_urls):
                seg_filename = os.path.basename(urlparse(seg_url).path)
                seg_local_path = os.path.join(dh_segment_dir, seg_filename)
                await run_in_threadpool(_download_and_save_file, seg_url, seg_local_path)
                
                local_segment_urls.append(get_relative_url(seg_local_path, request))
                local_segment_paths.append(seg_local_path) # 存储本地路径
            
            result["data"]["urls"] = local_segment_urls
            log.info("All video segments downloaded and saved.")

        # V2 修正: 使用新的嵌套结构更新任务状态
        success_details = {
            "message": "Digital human video and segments generated successfully.",
            "digital_human": {
                "video": {
                    "path": main_video_local_path,
                    "url": main_video_relative_url
                },
                "segments": {
                    "paths": local_segment_paths,
                    "urls": local_segment_urls
                },
                "segment_instructions": segments_json # 新增：保存分段指令
            }
        }
        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
            details=success_details
        )
        log.success(f"Digital human video and segments for task '{task_id}' processed successfully.")
        
        return result

    except Exception as e:
        # 捕获任何异常，记录错误日志，并更新任务状态为失败
        error_message = f"Failed to generate digital human video: {str(e)}"
        log.error(f"Digital human generation task '{task_id}' failed: {error_message}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": error_message}
        )
        # 向客户端返回一个HTTP 500错误
        raise HTTPException(status_code=500, detail=error_message)
    finally:
        # 无论成功或失败，都确保停止已启动的服务
        log.info(f"Stopping service '{heygem_service_name}' for task '{task_id}'.")
        service_controller.stop(heygem_service_name)
        log.info(f"Service '{heygem_service_name}' stopped.")
