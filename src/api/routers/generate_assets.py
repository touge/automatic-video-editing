
import os
import sys
from fastapi import APIRouter, Depends, HTTPException, Body, BackgroundTasks
from pydantic import BaseModel
from typing import Literal

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.core.task_manager import TaskManager
from src.api.security import verify_token
from src.logger import log
from starlette.concurrency import run_in_threadpool
from src.logic.assets_generator import AssetsGenerator
from src.core.scene_validator import SceneValidator

#✅ 新增：导入控制器
from src.core.service_controller import ServiceController
service_name = "LexiVisionAI"

router = APIRouter(
    prefix="/tasks",
    tags=["Scenes & Assets - Scenes and Assets"],
    dependencies=[Depends(verify_token)]
)

async def _prepare_assets_task(task_id: str):
    """Background task: Find, download, and validate video assets for all scenes."""
    task_manager = TaskManager(task_id)
    step_name = "asset_generation"

    #######################性能改进，使用ServiceController动态控制第三方服务##################
    service_controller = ServiceController()  # ✅ 新增：初始化服务控制器
    # ✅ 新增：安全启动服务，阻塞确认关键字
    try:
        # ✅ 新增：使用更可靠的关键字 "Application startup complete."
        service_controller.safe_start(service_name, keyword="Application startup complete.", timeout=60)
    except RuntimeError as e:
        log.error(str(e))
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": str(e)}
        )
        return  # ✅ 中止任务，防止继续执行
    #######################性能改进，使用ServiceController动态控制第三方服务##################

    try:
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step=step_name,
            details={"message": "Video asset acquisition task has started."}
        )
        
        # 在处理之前验证和修复场景文件
        log.info("Running scene validation before asset generation...")
        validator = SceneValidator(task_id)
        if not validator.validate_and_fix():
            raise RuntimeError("Scene validation and fixing failed. Cannot proceed with asset generation.")
        log.success("Scene validation completed.")

        preprocessor = AssetsGenerator(task_id)
        await run_in_threadpool(preprocessor.run)
        
        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
            details={"message": "All video assets have been successfully acquired and validated."}
        )
        log.success(f"Video asset acquisition task '{task_id}' completed successfully.")
    except Exception as e:
        error_message = f"Video asset acquisition failed: {str(e)}"
        log.error(f"Background video asset acquisition task '{task_id}' failed: {error_message}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": error_message}
        )
    finally:
        # ✅ 服务关闭
        service_controller.stop(service_name)
        log.info(f"{service_name} service has been stopped.")


@router.post("/{task_id}/assets", summary="Prepare all video assets (Async)")
async def prepare_assets(task_id: str, background_tasks: BackgroundTasks):
    """
    **Step 1**: Finds, downloads, and validates video assets for all sub-scenes in `final_scenes.json`.
    
    - **Input**: `final_scenes.json`
    - **Output**: A new `final_scenes_assets.json` file, which includes all sub-scenes with their corresponding `asset_path`.
    """
    task_manager = TaskManager(task_id)
    step_name = "asset_generation"

    scenes_path = task_manager.get_file_path('final_scenes')
    if not os.path.exists(scenes_path):
        raise HTTPException(status_code=404, detail=f"Prerequisite file 'final_scenes.json' not found for task '{task_id}'. Cannot start asset preparation.")

    background_tasks.add_task(_prepare_assets_task, task_id)
    
    message = "Video asset acquisition task submitted successfully. Awaiting processing."
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
