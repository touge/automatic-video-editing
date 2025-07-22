import os  # 导入操作系统相关的库
import re  # 导入正则表达式处理库
import json  # 导入JSON序列化库
from src.core.task_manager import TaskManager  # 从核心模块导入任务管理器
from src.core.scenes_process import SceneProcess  # 从逻辑模块导入场景生成器
from src.logger import log  # 从日志模块导入日志记录器

class SceneGenerator:  # 定义一个场景分析器类
    """
    负责分析脚本并生成带关键字的场景。
    不处理素材下载。
    """
    def __init__(self, task_id: str):  # 构造函数，接收任务ID
        if not task_id:  # 如果未提供task_id，抛出错误
           raise ValueError("A task_id must be provided.")
        
        self.task_id = task_id  # 保存任务ID
        self.task_manager = TaskManager(task_id)  # 初始化任务管理器
        self.scene_process = SceneProcess(task_id)  # 初始化场景生成器


    def run(self):
        log.info(f"--- Starting Scene Analysis for Task ID: {self.task_id} ---")

        # This step runs the scene splitting and keyword generation.
        self.scene_process.run()

        # After running, we can confirm the output file exists and get its info.
        final_scenes_path = self.task_manager.get_file_path('final_scenes')
        if not os.path.exists(final_scenes_path):
            raise RuntimeError("SceneGenerator ran but did not produce the final_scenes.json file.")

        scenes = SceneProcess.load_final_scenes(self.task_id)
        # print(f"scenes: {scenes}")
        
        log.success(f"Scene analysis complete. Found {len(scenes)} scenes.")

        return {
            "scenes_path": final_scenes_path,
            "scenes_count": len(scenes)
        }