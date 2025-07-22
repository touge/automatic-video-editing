
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

router = APIRouter(
    prefix="/tasks",
    tags=["Scenes & Assets - Scenes and Assets"],
    dependencies=[Depends(verify_token)]
)

async def _prepare_assets_task(task_id: str):
    """Background task: Find, download, and validate video assets for all scenes."""
    task_manager = TaskManager(task_id)
    step_name = "asset_generation"
    try:
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step=step_name,
            details={"message": "Video asset acquisition task has started."}
        )
        
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
