import os
from src.core.task_manager import TaskManager
from src.logic.scene_generator import SceneGenerator
from src.logger import log

class SceneAnalyzer:
    """
    This class is responsible for analyzing the script and generating scenes with keywords.
    It does NOT handle asset downloading.
    """
    def __init__(self, task_id: str):
        if not task_id:
            raise ValueError("A task_id must be provided.")
        
        self.task_id = task_id
        self.task_manager = TaskManager(task_id)
        self.scene_generator = SceneGenerator(task_id)

    def run(self):
        log.info(f"--- Starting Scene Analysis for Task ID: {self.task_id} ---")

        # This step runs the scene splitting and keyword generation.
        self.scene_generator.run()

        # After running, we can confirm the output file exists and get its info.
        final_scenes_path = self.task_manager.get_file_path('final_scenes')
        if not os.path.exists(final_scenes_path):
            raise RuntimeError("SceneGenerator ran but did not produce the final_scenes.json file.")

        scenes = SceneGenerator.load_final_scenes(self.task_id)
        
        log.success(f"Scene analysis complete. Found {len(scenes)} scenes.")

        return {
            "scenes_path": final_scenes_path,
            "scenes_count": len(scenes)
        }
