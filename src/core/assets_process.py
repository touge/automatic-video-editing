
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
        """
        为所有子场景查找并匹配素材。

        Args:
            main_scenes (list): 包含主场景信息的列表。

        Returns:
            tuple[list, bool]: 返回更新后的主场景列表和一个表示操作是否成功的布尔值。
        """
        # 初始化素材管理器
        asset_manager = AssetManager(config, self.task_manager.task_id)
        
        # 从主场景列表中提取所有子场景，构建一个扁平化的列表
        all_sub_scenes = [
            sub_scene
            for main_scene in main_scenes
            for sub_scene in main_scene.get('scenes', [])
        ]
        # print(f"all_sub_scenes: {all_sub_scenes}")
        # import sys;sys.exit(0)
        
        # 使用 tqdm 创建一个进度条，用于可视化素材查找过程
        sub_scenes_iterable = tqdm(all_sub_scenes, desc="Finding Assets", unit="sub-scene")
        # 从配置中获取在线搜索的次数，默认为 10
        online_search_count = config.get('asset_search', {}).get('online_search_count', 10)

        # 遍历所有子场景
        for i, sub_scene in enumerate(sub_scenes_iterable):
            # 更新进度条的描述，显示当前处理进度
            sub_scenes_iterable.set_description(f"Finding Asset {i+1}/{len(all_sub_scenes)}")
            
            # 获取子场景的搜索关键词
            keywords = sub_scene.get('keys', [])
            # 如果关键词列表为空，则记录错误并终止函数
            if not keywords:
                log.error(f"Sub-scene {i+1} is missing keywords. Aborting.")
                return main_scenes, False

            # 检查子场景是否已经有关联的素材路径，并且该文件存在
            if sub_scene.get('asset_path') and os.path.exists(sub_scene.get('asset_path')):
                # 如果存在缓存的素材，则记录调试信息并跳过当前循环
                log.debug(f"Found cached asset for sub-scene {i+1}")
                continue

            # 如果没有缓存素材，则调用素材管理器的 find_assets_for_scene 方法为当前子场景查找素材
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