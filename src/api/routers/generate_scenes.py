import os
import sys
from typing import Optional
from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.logic.scene_generator import SceneGenerator
from src.core.task_manager import TaskManager
from src.api.security import verify_token
from src.logger import log
from src.utils import get_relative_url

#✅ 新增：导入控制器
from src.core.service_controller import ServiceController
service_name = "Ollama"

router = APIRouter(
    prefix="/tasks",
    tags=["场景和素材 - Scenes and Assets"],
    dependencies=[Depends(verify_token)]
)

class SceneAnalysisRequest(BaseModel):
    """
    JSON structure for scene analysis request. This is currently empty as no payload is required.
    """
    pass

async def _run_analysis_task(task_id: str, request: Request):
    """Background task: Perform scene analysis and keyword generation."""
    task_manager = TaskManager(task_id)
    step_name = "scene_generation"

    #######################性能改进，使用ServiceController动态控制第三方服务##################
    service_controller = ServiceController()  # ✅ 新增：初始化服务控制器
    # ✅ 新增：安全启动服务，阻塞确认关键字
    try:
        # ✅ 新增：使用更可靠的关键字 "Listening on"
        service_controller.safe_start(service_name, timeout=60)
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
            details={"message": "Scene analysis and keyword generation task has started."}
        )

        srt_path = task_manager.get_file_path('final_srt')
        if not os.path.exists(srt_path):
            raise FileNotFoundError(f"Prerequisite file 'final.srt' not found. Please generate subtitles first.")

        # 从 status.json 获取 video_style
        status_data = task_manager.get_task_status()
        video_style = status_data.get("video_style", "default")
        
        log.info(f"Retrieved video_style '{video_style}' for task '{task_id}'.")

        preprocessor = SceneGenerator(task_id, style=video_style)
        result = await run_in_threadpool(preprocessor.run)

        scenes_url = get_relative_url(result['scenes_path'], request)

        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step=step_name,
            details={
                "message": "Scene analysis and keyword generation completed successfully.",
                "scenes_url": scenes_url,
                "summary": {
                    "scenes_count": result["scenes_count"]
                },
                "final_scenes_path": result["scenes_path"]
            }
        )
        log.success(f"Scene analysis task '{task_id}' completed successfully.")
    except Exception as e:
        error_message = f"Scene analysis failed: {str(e)}"
        log.error(f"Background scene analysis task '{task_id}' failed: {error_message}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            step=step_name,
            details={"message": error_message}
        )
    finally:
        # ✅ 服务关闭
        service_controller.stop(service_name)
        log.info(f"{service_name} service has been stopped.")

@router.post("/{task_id}/scenes", summary="分析场景并生成关键词/Analyze scenes and generate keywords (Async)")
async def scenes_analysis(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    payload: SceneAnalysisRequest = None # Payload is no longer used but kept for compatibility
):
    """
    Performs scene analysis and keyword generation for a specific task (asynchronously).
    Clients should poll /tasks/{task_id}/status to get progress and results.

    Includes two stages:
    1. Scene splitting: Extracts structured scenes from the uploaded script (original.txt).
    2. Keyword generation: Extracts keywords for each scene and shot.

    Upon completion, a final_scenes.json file will be generated.
    """
    try:
        task_manager = TaskManager(task_id)
        step_name = "scene_generation"

        srt_path = task_manager.get_file_path('final_srt')
        if not os.path.exists(srt_path):
            raise HTTPException(status_code=404, detail=f"Prerequisite file 'final.srt' not found for task '{task_id}'. Cannot start scene analysis.")

        background_tasks.add_task(_run_analysis_task, task_id, request)

        message = "Scene analysis task submitted successfully. Awaiting processing."
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

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Missing file for analysis task: {e}")

    except Exception as e:
        log.error(f"Failed to submit analysis task '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")
