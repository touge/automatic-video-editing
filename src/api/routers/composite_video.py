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
from src.utils import get_relative_url

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
    segments: List[SegmentSpec]
    main_clip_params: Optional[ClipParams] = None
    base_video_volume: float = 1.0
    output_filename: str = "final_video_composited.mp4"

# --- Background Task ---
async def _composite_task(task_id: str, request_body: CompositeDigitalHumanRequest, http_request: Request):
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
        
        # 将请求体中的 Pydantic 模型（segments）列表转换为字典列表
        # `exclude_unset=True` 确保只转换那些在请求中显式设置过的字段
        specs_as_dicts = [seg.model_dump(exclude_unset=True) for seg in request_body.segments]
        
        # 将主剪辑参数的 Pydantic 模型转换为字典，如果参数存在的话
        main_clip_params_dict = request_body.main_clip_params.model_dump(exclude_unset=True) if request_body.main_clip_params else None

        # ---- 执行合成逻辑 ----
        # 使用 run_in_threadpool 将耗时的合成操作放到一个独立的线程池中执行
        # 这可以避免阻塞主事件循环，是异步编程中处理同步 I/O 的常用模式
        final_video_path = await run_in_threadpool(
            compositor.run,  # 调用合成器对象的 run 方法
            composition_specs=specs_as_dicts,
            output_filename=request_body.output_filename,
            main_clip_params=main_clip_params_dict,
            base_video_volume=request_body.base_video_volume
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
                "composited_video_url": video_url, # 记录最终视频的 URL
                "composited_video_path": final_video_path # 记录最终视频的文件路径
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

@router.post("/{task_id}/composite-digital-human", summary="Composite digital human segments onto the main video (Async)")
async def composite_digital_human(task_id: str, background_tasks: BackgroundTasks, http_request: Request, body: CompositeDigitalHumanRequest):
    task_manager = TaskManager(task_id)
    
    # Basic validation
    status = task_manager.get_task_status()
    if not status.get("details", {}).get("digital_human"):
        raise HTTPException(status_code=404, detail="Digital human data not found in task status. Please run digital human generation first.")

    background_tasks.add_task(_composite_task, task_id, body, http_request)
    
    message = "Digital human composition task submitted successfully."
    return {"task_id": task_id, "status": "SUBMITTED", "message": message}
