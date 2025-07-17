import os
import sys
from fastapi import APIRouter, Depends, Request, HTTPException, Body
from pydantic import BaseModel
from typing import Optional

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.logic.video_composer_logic import VideoComposition
from src.core.task_manager import TaskManager
from src.api.security import verify_token
from src.config_loader import config
from src.logger import log

router = APIRouter(
    prefix="/tasks",
    tags=["Composition - 视频合成"],
    dependencies=[Depends(verify_token)]
)

class CompositionParams(BaseModel):
    embed_subtitles: bool = True

@router.post("/{task_id}/compose", summary="合成最终视频")
async def compose_video(
    request: Request,
    task_id: str,
    params: CompositionParams = Body(CompositionParams(), description="视频合成参数。")
):
    """
    将所有处理好的场景、素材和音频合成为最终的视频文件。

    - **依赖**: 此步骤要求 `final_scenes.json` 和 `final_audio.wav` 文件已存在于任务目录中。
    - **embed_subtitles**: 是否将字幕硬编码到视频中。默认为 `True`。
    """
    try:
        task_manager = TaskManager(task_id)
        
        # 从配置中获取场景配置，如果不存在则默认为空字典
        scene_config = config.get('composition_settings', {}).get('scene_config', {})
        
        composer = VideoComposition(
            task_id=task_id, 
            burn_subtitle=params.embed_subtitles, 
            scene_config=scene_config
        )
        composer.run()

        video_path = task_manager.get_file_path('final_video')
        
        # Construct the URL for the final_video.mp4 file
        relative_path = os.path.relpath(video_path, start=project_root)
        url_path = f"static/{relative_path.replace(os.path.sep, '/')}"
        video_url = f"{str(request.base_url).rstrip('/')}/{url_path}"

        return {
            "task_id": task_id,
            "status": "success",
            "message": "Video composition completed successfully.",
            "video_url": video_url
        }
    except FileNotFoundError as e:
        log.error(f"Prerequisite file not found for composition in task '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=f"Prerequisite file not found for composition: {e}")
    except Exception as e:
        log.error(f"Failed to compose video for task '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
