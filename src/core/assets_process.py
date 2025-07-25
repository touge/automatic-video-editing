
import os
import re
import json
from tqdm import tqdm
from pathlib import Path

# 导入配置文件、核心模块、日志模块
from src.config_loader import config
from src.logger import log
from src.core.task_manager import TaskManager
from src.core.asset_manager import AssetManager
from src.utils import get_video_duration

class AssetsProcess:
    def __init__(self, task_id: str):
        # 初始化 SceneGenerator 实例，绑定任务 ID
        if not task_id:
            raise ValueError("A task_id must be provided.")
        self.task_manager = TaskManager(task_id)
        # 获取最终分镜文件路径
        self.scenes_path = self.task_manager.get_file_path('final_scenes')

        # 最终分镜文件 + 素材资源
        self.assets_scenes_path = self.task_manager.get_file_path('final_scenes_with_assets')


    def run(self):
        # 打印日志，开始素材准备流程
        log.info(f"--- Starting Asset Preparation for Task ID: {self.task_manager.task_id} ---")

        if os.path.exists(self.assets_scenes_path):
            log.success(f"The final scene material cache file for task {self.task_manager.task_id} already exists. Nothing to do.")
            log.info(f"You can find the file at: {self.assets_scenes_path}")
            return

        
        # 检查文件是否存在，否则抛出异常
        if not os.path.exists(self.scenes_path):
            raise FileNotFoundError(f"Required file 'final_scenes.json' not found.")

        # 载入最终分镜数据（包含主分镜及子镜头）
        main_scenes = self.load_final_scenes(self.task_manager.task_id)
        
        # 数据加载失败则中断
        if not main_scenes:
            raise ValueError("Failed to load or parse 'final_scenes.json'.")

        # 核心逻辑：为每个子镜头查找素材资源
        scenes_with_assets, all_found = self._find_assets_for_sub_scenes(main_scenes)
        
        # 若未能完成素材查找流程，则中断抛出异常
        if not all_found:
            raise RuntimeError("Failed to find assets for all sub-scenes.")

        # 清洗运行时数据（如中间状态、调试信息等）
        cleaned_scenes = self._clean_runtime_data(scenes_with_assets)
        
        # 将清理后的分镜结构写入 JSON 文件
        with open(self.assets_scenes_path, 'w', encoding='utf-8') as f:
            json.dump(cleaned_scenes, f, ensure_ascii=False, indent=2)

        # 打印完成日志
        log.success(f"Asset preparation complete. Data saved to {self.assets_scenes_path}")

    @classmethod
    def load_final_scenes(cls, task_id: str) -> list:
        # 载入指定任务的最终分镜数据
        task_manager = TaskManager(task_id)
        final_scenes_path = task_manager.get_file_path('final_scenes')
        
        if not os.path.exists(final_scenes_path):
            log.error(f"Final scenes file does not exist: {final_scenes_path}")
            return []
            
        try:
            with open(final_scenes_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Error loading final scenes data: {e}")
            return []

    def _find_assets_for_sub_scenes(self, main_scenes: list) -> tuple[list, bool]:
        asset_manager = AssetManager(config, self.task_manager.task_id)
        
        all_sub_scenes = [
            sub_scene
            for main_scene in main_scenes
            for sub_scene in main_scene.get('scenes', [])
        ]
        
        sub_scenes_iterable = tqdm(all_sub_scenes, desc="Finding Assets", unit="sub-scene")
        online_search_count = config.get('asset_search', {}).get('online_search_count', 10)

        for i, sub_scene in enumerate(sub_scenes_iterable):
            sub_scenes_iterable.set_description(f"Finding Asset {i+1}/{len(all_sub_scenes)}")
            
            keywords = sub_scene.get('keys', [])
            if not keywords:
                log.error(f"Sub-scene {i+1} is missing keywords. Aborting.")
                return main_scenes, False

            if sub_scene.get('asset_path') and os.path.exists(sub_scene.get('asset_path')):
                log.debug(f"Found cached asset for sub-scene {i+1}")
                continue

            found_video_info_list = asset_manager.find_assets_for_scene(sub_scene, online_search_count)
            
            if not found_video_info_list:
                # AssetManager 已经记录了详细的错误日志，这里直接返回失败
                return main_scenes, False

            # AssetManager 返回的是包含单个已验证素材信息的列表
            video_info = found_video_info_list[0]
            
            # 更新子场景信息
            sub_scene['asset_path'] = video_info['local_path'].replace(os.sep, '/')
            # AssetManager 现在不返回时长，我们需要自己获取
            sub_scene['actual_duration'] = get_video_duration(video_info['local_path'])
        
        return main_scenes, True
    
    def _clean_runtime_data(self, main_scenes: list) -> list:
        """Removes temporary runtime fields from scene data before saving."""
        import copy
        scenes_copy = copy.deepcopy(main_scenes)
        keys_to_remove = ['actual_duration']
        for main_scene in scenes_copy:
            for sub_scene in main_scene.get('scenes', []):
                for key in keys_to_remove:
                    if key in sub_scene:
                        del sub_scene[key]
        return scenes_copy