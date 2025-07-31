from src.logger import log
from src.core.task_manager import TaskManager
from src.core.assets_process import AssetsProcess

class AssetsGenerator:
    def __init__(self, task_id: str):
        self.task_id = task_id  # 保存任务ID
        self.task_manager = TaskManager(self.task_id)
        self.assets_process = AssetsProcess(self.task_id)  # 初始化场景生成器

    def run(self):
        log.info(f"--- Starting Scene Analysis for Task ID: {self.task_id} ---")
        self.assets_process.run()
        log.success(f"Scene analysis complete.")
