import os
import sys
from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks # Import BackgroundTasks
from starlette.concurrency import run_in_threadpool # Import run_in_threadpool

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.logic.scene_analyzer import SceneAnalyzer
from src.core.task_manager import TaskManager # Import TaskManager
from src.api.security import verify_token
from src.logger import log

router = APIRouter(
    prefix="/tasks",
    tags=["Analysis - 场景分析与素材准备"],
    dependencies=[Depends(verify_token)]
)

# Helper function to get relative URL path (duplicate from other routers, but kept for self-containment)
def _get_relative_url_path(file_path: str) -> str:
    relative_path = os.path.relpath(file_path, start=project_root)
    return f"static/{relative_path.replace(os.path.sep, '/')}"

async def _run_analysis_task(task_id: str, request_base_url: str):
    """Background task for running scene analysis and keyword generation."""
    task_manager = TaskManager(task_id)
    try:
        task_manager.update_task_status(TaskManager.STATUS_RUNNING, step="scene_analysis", details={"message": "Scene analysis and keyword generation in progress."})
        
        # Check for prerequisite file (final.srt)
        srt_path = task_manager.get_file_path('final_srt')
        if not os.path.exists(srt_path):
            raise FileNotFoundError(f"Required file 'final.srt' not found for task '{task_id}'. Please ensure subtitle generation is complete.")

        analyzer = SceneAnalyzer(task_id)
        # Run the blocking operation in a thread pool
        result = await run_in_threadpool(analyzer.run)

        scenes_url = f"{request_base_url.rstrip('/')}/{_get_relative_url_path(result['scenes_path'])}"

        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step="scene_analysis",
            details={
                "message": "Scene analysis and keyword generation completed.",
                "scenes_url": scenes_url,
                "summary": {
                    "scenes_count": result["scenes_count"]
                },
                "final_scenes_path": result["scenes_path"]
            }
        )
        log.info(f"Scene analysis for task '{task_id}' completed successfully.")
    except FileNotFoundError as e:
        log.error(f"Background scene analysis for task '{task_id}' failed due to missing prerequisite: {e}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            {"message": f"Scene analysis failed: Missing prerequisite file: {e}", "error": str(e)}
        )
    except Exception as e:
        log.error(f"Background scene analysis for task '{task_id}' failed: {e}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            {"message": f"Scene analysis failed: {e}", "error": str(e)}
        )

@router.post("/{task_id}/analysis", summary="分析场景并生成关键词 (异步)")
async def run_analysis(
    task_id: str,
    background_tasks: BackgroundTasks, # Inject BackgroundTasks
    request: Request
):
    """
    对指定任务异步执行场景分析和关键词生成。
    客户端应轮询 /tasks/{task_id}/status 接口以获取任务状态和结果。

    1.  **场景分割**: 基于字幕文件 (`final.srt`) 进行场景分割。
    2.  **关键词生成**: 为每个场景和镜头生成关键词。

    此端点将任务从“有字幕”阶段推进到“场景和关键词就绪”阶段，最终产出 `final_scenes.json` 文件。
    """
    try:
        task_manager = TaskManager(task_id)
        
        # Check for prerequisite file (final.srt) before submitting the task
        srt_path = task_manager.get_file_path('final_srt')
        if not os.path.exists(srt_path):
            raise HTTPException(status_code=404, detail=f"Required file 'final.srt' not found for task '{task_id}'. Please ensure subtitle generation is complete.")

        # Add the analysis task to background
        background_tasks.add_task(_run_analysis_task, task_id, str(request.base_url))
        
        task_manager.update_task_status(TaskManager.STATUS_PENDING, {"message": "Scene analysis task submitted."})
        
        return {
            "task_id": task_id,
            "status": TaskManager.STATUS_PENDING,
            "message": "Scene analysis task submitted. Please poll /tasks/{task_id}/status for updates."
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Prerequisite file not found for analysis: {e}")
    except Exception as e:
        log.error(f"Failed to submit analysis task for '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
