import os
import sys
from fastapi import APIRouter, Depends, Request, HTTPException

# Add project root to the Python path to allow module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.logic.scene_analyzer import SceneAnalyzer
from src.api.security import verify_token
from src.logger import log

router = APIRouter(
    prefix="/tasks",
    tags=["Analysis - 场景分析与素材准备"],
    dependencies=[Depends(verify_token)]
)

@router.post("/{task_id}/analysis", summary="分析场景并生成关键词")
async def run_analysis(request: Request, task_id: str):
    """
    对指定任务执行场景分析和关键词生成。
    1.  **场景分割**: 基于字幕文件 (`final.srt`) 进行场景分割。
    2.  **关键词生成**: 为每个场景和镜头生成关键词。

    此端点将任务从“有字幕”阶段推进到“场景和关键词就绪”阶段，最终产出 `final_scenes.json` 文件。
    """
    try:
        analyzer = SceneAnalyzer(task_id)
        result = analyzer.run()

        # Construct the URL for the final_scenes.json file
        relative_path = os.path.relpath(result["scenes_path"], start=project_root)
        url_path = f"static/{relative_path.replace(os.path.sep, '/')}"
        scenes_url = f"{str(request.base_url).rstrip('/')}/{url_path}"

        return {
            "task_id": task_id,
            "status": "success",
            "message": "Scene analysis and keyword generation completed.",
            "scenes_url": scenes_url,
            "summary": {
                "scenes_count": result["scenes_count"]
            }
        }
    except FileNotFoundError as e:
        log.error(f"Prerequisite file not found for task '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=f"Prerequisite file not found: {e}")
    except Exception as e:
        log.error(f"Failed to run analysis for task '{task_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
