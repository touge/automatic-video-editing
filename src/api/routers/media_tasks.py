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
from src.logic.video_composer_logic import VideoCompositionLogic
from src.api.security import verify_token
from src.logger import log
from starlette.concurrency import run_in_threadpool

router = APIRouter(
    prefix="/tasks",
    tags=["Composition Steps - 视频分步合成"],
    dependencies=[Depends(verify_token)]
)

class AssembleParams(BaseModel):
    stage: Literal["silent", "audio", "full"] = "full"

async def _prepare_assets_task(task_id: str):
    task_manager = TaskManager(task_id)
    try:
        task_manager.update_task_status(TaskManager.STATUS_RUNNING, step="asset_preparation", details={"message": "Asset preparation in progress."})
        logic = VideoCompositionLogic(task_id)
        await run_in_threadpool(logic.prepare_all_assets)
        task_manager.update_task_status(TaskManager.STATUS_SUCCESS, step="asset_preparation", details={"message": "Asset preparation completed."})
    except Exception as e:
        log.error(f"Asset preparation for task '{task_id}' failed: {e}", exc_info=True)
        task_manager.update_task_status(TaskManager.STATUS_FAILED, step="asset_preparation", details={"message": f"Asset preparation failed: {e}", "error": str(e)})

async def _assemble_video_task(task_id: str, stage: str, burn_subtitle: bool):
    task_manager = TaskManager(task_id)
    try:
        task_manager.update_task_status(TaskManager.STATUS_RUNNING, step=f"assembly_{stage}", details={"message": f"Video assembly for stage '{stage}' in progress."})
        logic = VideoCompositionLogic(task_id)
        await run_in_threadpool(logic.run_assembly_stage, stage=stage, burn_subtitle=burn_subtitle)
        task_manager.update_task_status(TaskManager.STATUS_SUCCESS, step=f"assembly_{stage}", details={"message": f"Video assembly for stage '{stage}' completed."})
    except Exception as e:
        log.error(f"Video assembly for task '{task_id}' stage '{stage}' failed: {e}", exc_info=True)
        task_manager.update_task_status(TaskManager.STATUS_FAILED, step=f"assembly_{stage}", details={"message": f"Video assembly failed: {e}", "error": str(e)})

@router.post("/{task_id}/assets", summary="准备所有视频素材 (异步)")
async def prepare_assets(task_id: str, background_tasks: BackgroundTasks):
    """
    **第1步**: 为 `final_scenes.json` 中的所有子场景查找、下载并验证视频素材。
    
    - **输入**: `final_scenes.json`
    - **输出**: 一个新的 `final_scenes_assets.json` 文件，其中包含了所有子场景及其匹配到的 `asset_path`。
    """
    task_manager = TaskManager(task_id)
    background_tasks.add_task(_prepare_assets_task, task_id)
    task_manager.update_task_status(TaskManager.STATUS_PENDING, {"message": "Asset preparation task submitted."})
    return {"task_id": task_id, "status": "PENDING", "message": "Asset preparation task submitted."}

@router.post("/{task_id}/assemble", summary="分阶段合成视频 (异步)")
async def assemble_video(task_id: str, background_tasks: BackgroundTasks, params: AssembleParams = Body(AssembleParams())):
    """
    **第2步**: 执行视频合成。可以分阶段进行以方便调试。
    
    - **输入**: `final_scenes_assets.json` 和 `final_audio.wav`
    - **输出**: 根据 `stage` 参数，生成相应的中间或最终视频文件。
        - `silent`: 只拼接视频片段，生成一个无声的视频 (`silent_video.mp4`)。
        - `audio`: 在无声视频的基础上，合并音频 (`video_with_audio.mp4`)。
        - `full`: 在有声视频的基础上，烧录字幕，生成最终版 (`final_video.mp4`)。
    """
    task_manager = TaskManager(task_id)
    # For now, burn_subtitle is hardcoded to True for the 'full' stage.
    # This could be made a parameter in the future.
    burn_subtitle = True if params.stage == "full" else False
    background_tasks.add_task(_assemble_video_task, task_id, params.stage, burn_subtitle)
    task_manager.update_task_status(TaskManager.STATUS_PENDING, {"message": f"Video assembly task for stage '{params.stage}' submitted."})
    return {"task_id": task_id, "status": "PENDING", "message": f"Video assembly task for stage '{params.stage}' submitted."}
