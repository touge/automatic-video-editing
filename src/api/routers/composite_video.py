import os
import sys
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from typing import List, Optional, Union

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.core.task_manager import TaskManager
from src.logic.digital_human_compositor import DigitalHumanCompositor
from src.api.security import verify_token
from src.logger import log
from starlette.concurrency import run_in_threadpool
from src.utils import get_relative_url, to_slash_path

router = APIRouter(
    prefix="/tasks",
    tags=["视频合成 - Video Composition"],
    dependencies=[Depends(verify_token)]
)

# --- Pydantic Models for API Request Body ---

class Position(BaseModel):
    x: Union[int, str]
    y: Union[int, str]

class ClipParams(BaseModel):
    start: float = 0.0
    duration: Optional[float] = None

class SegmentSpec(BaseModel):
    start_time: Optional[float] = None
    clip_params: Optional[ClipParams] = None
    volume: Optional[float] = None
    size: Optional[str] = None
    position: Optional[Position] = None

class CompositeDigitalHumanRequest(BaseModel):
    segments: Optional[List[SegmentSpec]] = None
    main_clip_params: Optional[ClipParams] = None
    base_video_volume: float = 1.0
    output_filename: str = "final_video_composited.mp4"

# --- Background Task ---
async def _composite_task(task_id: str, request_body: Optional[CompositeDigitalHumanRequest], http_request: Request):
    # 初始化任务管理器，用于跟踪和更新任务状态
    task_manager = TaskManager(task_id)

    # 定义当前任务步骤的名称
    step_name = "digital_human_composition"
    
    try:
        # ---- 任务开始 ----
        # 更新任务状态为“正在运行”，并记录开始信息
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step=step_name,
            details={"message": "Digital human composition task has started."}
        )
        
        # 初始化数字人合成器，这是执行实际合成逻辑的核心类
        compositor = DigitalHumanCompositor(task_id)
        
        # ---- 参数准备与智能合并 ----
        
        # 1. 初始化顶级参数的默认值
        main_clip_params_dict = None
        base_video_volume = 1.0
        output_filename = "final_video_composited.mp4"

        # 2. 获取任务状态和默认值，供后续使用
        status = task_manager.get_task_status()
        # 修正：直接从 status 对象获取，而不是从不存在的 details 获取
        video_info = status.get("video_info", {})
        main_video_resolution = video_info.get("resolution", "1920x1080")
        default_position = {"x": "center", "y": "center"}
        default_volume = 0

        # 3. 处理顶级参数（如果用户提供了）
        if request_body:
            if request_body.main_clip_params:
                main_clip_params_dict = request_body.main_clip_params.model_dump(exclude_unset=True)
            # 使用 getattr 安全地获取可能不存在的属性
            base_video_volume = getattr(request_body, 'base_video_volume', base_video_volume)
            output_filename = getattr(request_body, 'output_filename', output_filename)

        # 4. 处理 segments 列表
        specs_as_dicts = []
        if request_body and request_body.segments:
            # --- 情况1: 用户提供了 segments ---
            log.info("Request body contains segments. Applying smart completion logic.")
            for seg in request_body.segments:
                spec = seg.model_dump(exclude_unset=False) # 使用 False 确保所有字段都存在，便于检查
                
                # 智能补全缺失的字段
                if spec.get('volume') is None:
                    spec['volume'] = default_volume
                if spec.get('size') is None:
                    spec['size'] = main_video_resolution
                if spec.get('position') is None:
                    spec['position'] = default_position
                
                specs_as_dicts.append(spec)
        else:
            # --- 情况2: 用户未提供 segments，完全使用默认值 ---
            log.info("No segments in request body. Using default values from status.json.")
            # 修正：直接从 status 对象获取
            digital_human_data = status.get("digital_human", {})
            if not digital_human_data or "segments" not in digital_human_data:
                raise ValueError("Digital human segments data not found in task status.")

            for seg_info in digital_human_data["segments"]:
                start_str = seg_info.get("start")
                end_str = seg_info.get("end")

                def parse_hhmmss_to_seconds(time_str):
                    is_negative = time_str.startswith('-')
                    parts = time_str.strip('-').split(':')
                    seconds = sum(int(p) * 60**i for i, p in enumerate(reversed(parts)))
                    return -seconds if is_negative else seconds

                start_seconds = parse_hhmmss_to_seconds(start_str)
                end_seconds = parse_hhmmss_to_seconds(end_str)
                
                duration = abs(end_seconds - start_seconds)

                specs_as_dicts.append({
                    "start_time": start_seconds,
                    "clip_params": {
                        "start": 0,
                        "duration": duration
                    },
                    "volume": default_volume,
                    "size": main_video_resolution,
                    "position": {
                        "x": "(W-w)/2",
                        "y": "(H-h)/2"
                    }
                })
        
        # ---- 执行合成逻辑 ----
        final_video_path = await run_in_threadpool(
            compositor.run,
            composition_specs=specs_as_dicts,
            output_filename=output_filename,
            main_clip_params=main_clip_params_dict,
            base_video_volume=base_video_volume
        )
        
        # ---- 任务成功 ----
        # 根据合成后的视频文件路径和 HTTP 请求，生成一个相对可访问的 URL
        video_url = get_relative_url(final_video_path, http_request)

        # 更新任务状态为“成功”
        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
            details={
                "message": "Digital human composition completed successfully.",
                "composited_video_url": video_url,
                "composited_video_path": to_slash_path(final_video_path)
            }
        )
        # 记录成功日志
        log.success(f"Digital human composition task '{task_id}' completed successfully.")
        
    except Exception as e:
        # ---- 任务失败 ----
        # 捕获所有异常，构建错误信息
        error_message = f"Digital human composition failed: {str(e)}"
        # 记录错误日志，包括异常信息
        log.error(f"Background composition task '{task_id}' failed: {error_message}", exc_info=True)
        # 更新任务状态为“失败”
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": error_message}
        )

# --- API Endpoint ---

@router.post("/{task_id}/composite-digital-human", summary="将数字人体片段合成到主视频上/Composite digital human segments onto the main video (Async)")
async def composite_digital_human(task_id: str, background_tasks: BackgroundTasks, http_request: Request, body: Optional[CompositeDigitalHumanRequest] = None):
    task_manager = TaskManager(task_id)
    
    # Basic validation
    status = task_manager.get_task_status()
    # 修正：直接从 status 对象获取
    if not status.get("digital_human"):
        raise HTTPException(status_code=404, detail="Digital human data not found in task status. Please run digital human generation first.")

    background_tasks.add_task(_composite_task, task_id, body, http_request)
    
    message = "Digital human composition task submitted successfully."
    return {"task_id": task_id, "status": "SUBMITTED", "message": message}
