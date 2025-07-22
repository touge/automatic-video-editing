import os
import sys
from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks  # 引入 FastAPI 所需模块，包括后台任务支持
from starlette.concurrency import run_in_threadpool  # 用于在后台线程中运行阻塞操作

# 设置项目根目录，使得可以正确导入项目模块
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)  # 将项目根目录添加到系统路径，确保模块可被正确引入

# 引入项目内部模块
from src.logic.scene_generator import SceneGenerator
from src.core.task_manager import TaskManager
from src.api.security import verify_token
from src.logger import log
from src.utils import get_relative_url

# 创建路由对象，用于挂载API路径和标签
router = APIRouter(
    prefix="/tasks",
    tags=["Scenes & Assets - Scenes and Assets"],
    dependencies=[Depends(verify_token)]
)

# 定义后台任务函数，执行场景分析和关键词生成
async def _run_analysis_task(task_id: str, request: Request):
    """Background task: Perform scene analysis and keyword generation."""
    task_manager = TaskManager(task_id)
    step_name = "scene_generation"
    try:
        task_manager.update_task_status(
            TaskManager.STATUS_RUNNING,
            step=step_name,
            details={"message": "Scene analysis and keyword generation task has started."}
        )

        srt_path = task_manager.get_file_path('final_srt')
        if not os.path.exists(srt_path):
            raise FileNotFoundError(f"Prerequisite file 'final.srt' not found. Please generate subtitles first.")
        
        preprocessor = SceneGenerator(task_id)
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

# 定义API接口：提交场景分析任务（异步）
@router.post("/{task_id}/scenes", summary="Analyze scenes and generate keywords (Async)")
async def scenes_analysis(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: Request
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
