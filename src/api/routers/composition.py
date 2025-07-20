import os
import sys
import os
import sys
from fastapi import APIRouter, Depends, Request, HTTPException, Body, BackgroundTasks # Import BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any # Import Dict, Any
from starlette.concurrency import run_in_threadpool # Import run_in_threadpool

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.logic.video_composer_logic import VideoComposition
from src.core.task_manager import TaskManager
from src.api.security import verify_token
from src.config_loader import config
from src.logger import log
from src.logic.scene_generator import SceneGenerator
import json

router = APIRouter(
    prefix="/tasks",
    tags=["Composition - 视频合成"],
    dependencies=[Depends(verify_token)]
)

class CompositionParams(BaseModel):
    embed_subtitles: bool = False

# Helper function to get relative URL path (duplicate from other routers, but kept for self-containment)
def _get_relative_url_path(file_path: str) -> str:
    relative_path = os.path.relpath(file_path, start=project_root)
    return f"static/{relative_path.replace(os.path.sep, '/')}"

async def _compose_video_task(task_id: str, params: CompositionParams, request_base_url: str):
    """Background task for composing video."""
    task_manager = TaskManager(task_id)
    try:
        task_manager.update_task_status(TaskManager.STATUS_RUNNING, step="video_composition", details={"message": "Video composition in progress."})
        
        # Check for prerequisite files
        final_scenes_path = task_manager.get_file_path('final_scenes')
        final_audio_path = task_manager.get_file_path('final_audio')
        
        if not os.path.exists(final_scenes_path):
            raise FileNotFoundError(f"Required file 'final_scenes.json' not found for task '{task_id}'.")
        if not os.path.exists(final_audio_path):
            raise FileNotFoundError(f"Required file 'final_audio.wav' not found for task '{task_id}'.")

        # Load scenes and check for empty ones
        scenes = SceneGenerator.load_final_scenes(task_id)
        if not scenes:
            raise ValueError("Failed to load or parse 'final_scenes.json'.")

        scene_generator = SceneGenerator(task_id)
        scenes_updated = False
        for i, scene in enumerate(scenes):
            # Correctly check for the 'scenes' key to identify main scenes that are empty.
            if not scene.get('scenes'):
                log.warning(f"Found an empty main scene (number: {scene.get('scene_number')}) in task '{task_id}'. Regenerating its sub-scenes.")
                
                # Use the correctly named method to regenerate the sub-scenes.
                updated_scene = scene_generator.regenerate_scenes_for_scene(scene)
                
                # Check if the regeneration was successful by seeing if sub-scenes were added.
                if updated_scene.get('scenes'):
                    scenes[i] = updated_scene  # Replace the old scene with the updated one.
                    scenes_updated = True
                    log.success(f"Successfully regenerated sub-scenes for main scene {scene.get('scene_number')}.")
                else:
                    log.error(f"Failed to regenerate sub-scenes for main scene {scene.get('scene_number')} in task '{task_id}'.")

        if scenes_updated:
            SceneGenerator.save_final_scenes(scenes, task_id)
            log.info(f"Successfully regenerated and saved shots for empty scenes in task '{task_id}'.")

        scene_config = config.get('composition_settings', {}).get('scene_config', {})
        
        composer = VideoComposition(
            task_id=task_id, 
            burn_subtitle=params.embed_subtitles, 
            scene_config=scene_config
        )
        # Run the blocking operation in a thread pool
        await run_in_threadpool(composer.run)

        video_path = task_manager.get_file_path('final_video')
        
        video_url = f"{request_base_url.rstrip('/')}/{_get_relative_url_path(video_path)}"

        task_manager.update_task_status(
            TaskManager.STATUS_SUCCESS,
            step="video_composition",
            details={"message": "Video composition completed successfully.", "video_url": video_url, "final_video_path": video_path}
        )
        log.info(f"Video composition for task '{task_id}' completed successfully.")
    except FileNotFoundError as e:
        log.error(f"Background video composition for task '{task_id}' failed due to missing prerequisite: {e}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            {"message": f"Video composition failed: Missing prerequisite file: {e}", "error": str(e)}
        )
    except Exception as e:
        log.error(f"Background video composition for task '{task_id}' failed: {e}", exc_info=True)
        task_manager.update_task_status(
            TaskManager.STATUS_FAILED,
            {"message": f"Video composition failed: {e}", "error": str(e)}
        )

@router.post("/{task_id}/compose", summary="合成最终视频 (异步)")
async def compose_video(
    task_id: str,
    background_tasks: BackgroundTasks, # Inject BackgroundTasks
    request: Request,
    params: CompositionParams = Body(CompositionParams(), description="视频合成参数。")
):
    """
    将所有处理好的场景、素材和音频合成为最终的视频文件。
    此操作会异步执行视频合成。客户端应轮询 /tasks/{task_id}/status 接口以获取任务状态和结果。

    - **依赖**: 此步骤要求 `final_scenes.json` 和 `final_audio.wav` 文件已存在于任务目录中。
    - **embed_subtitles**: 是否将字幕硬编码到视频中。默认为 `False`。
    """
    try:
        task_manager = TaskManager(task_id)
        
        # Check if prerequisite files exist before submitting the task
        final_scenes_path = task_manager.get_file_path('final_scenes')
        final_audio_path = task_manager.get_file_path('final_audio')
        
        if not os.path.exists(final_scenes_path):
            raise HTTPException(status_code=404, detail=f"Required file 'final_scenes.json' not found for task '{task_id}'. Please ensure scene generation is complete.")
        if not os.path.exists(final_audio_path):
            raise HTTPException(status_code=404, detail=f"Required file 'final_audio.wav' not found for task '{task_id}'. Please ensure audio generation is complete.")

        # Add the video composition task to background
        background_tasks.add_task(_compose_video_task, task_id, params, str(request.base_url))
        
        task_manager.update_task_status(TaskManager.STATUS_PENDING, {"message": "Video composition task submitted."})
        
        return {
            "task_id": task_id,
            "status": TaskManager.STATUS_PENDING,
            "message": "Video composition task submitted. Please poll /tasks/{task_id}/status for updates."
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Prerequisite file not found for composition: {e}")
    except Exception as e:
        log.error(f"Failed to submit video composition task for '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
