import json
from src.core.task_manager import TaskManager
from src.keyword_generator import KeywordGenerator
from src.config_loader import config
from src.logger import log

class SceneValidator:
    """
    负责验证和修复 final_scenes.json 文件中的数据完整性和正确性。
    """

    def __init__(self, task_id: str):
        """
        初始化验证器。

        Args:
            task_id (str): 当前任务的 ID。
        """
        self.task_id = task_id
        self.task_manager = TaskManager(task_id)

    def validate_and_fix(self):
        """
        加载、验证并修复 final_scenes.json 文件。
        如果发现不一致或不完整的数据，将尝试重新生成。
        """
        log.info(f"Starting validation and fixing for final_scenes.json of task '{self.task_id}'...")
        
        scenes_path = self.task_manager.get_file_path('final_scenes')
        try:
            with open(scenes_path, 'r', encoding='utf-8') as f:
                scenes_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.error(f"Could not read or parse final_scenes.json: {e}")
            return False

        max_retries = 5 # 设置最大重试次数，防止无限循环
        current_retry = 0

        while True:
            current_retry += 1
            if current_retry > max_retries:
                log.error(f"Exceeded maximum retries ({max_retries}) for scene validation. Some issues might persist.")
                break

            log.info(f"Validation pass {current_retry}/{max_retries} for final_scenes.json...")
            
            try:
                with open(scenes_path, 'r', encoding='utf-8') as f:
                    scenes_data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError) as e:
                log.error(f"Could not read or parse final_scenes.json: {e}")
                return False

            is_dirty_this_pass = False  # 标记当前循环数据是否被修改过
            keyword_gen = None  # 延迟初始化 KeywordGenerator

            for i, scene in enumerate(scenes_data):
                # 检查子场景列表是否存在且非空
                if not scene.get('scenes') or not isinstance(scene['scenes'], list):
                    log.warning(f"Scene {i+1} is missing 'scenes' list. Triggering regeneration.")
                    is_dirty_this_pass = True
                    if keyword_gen is None:
                        keyword_gen = KeywordGenerator(config) # 按需初始化
                    
                    # 重新生成这个场景
                    self._regenerate_scene(scene, keyword_gen)
                    continue

                # 检查每个子场景的字段
                for sub_scene in scene['scenes']:
                    is_invalid_time = 'time' not in sub_scene or not isinstance(sub_scene['time'], (int, float)) or sub_scene['time'] <= 0
                    is_missing_keys = 'keys' not in sub_scene or not sub_scene['keys']
                    is_missing_text = 'source_text' not in sub_scene or not sub_scene['source_text']

                    if is_invalid_time or is_missing_keys or is_missing_text:
                        log.warning(f"Scene {i+1} contains invalid sub-scene data. Triggering regeneration.")
                        log.debug(f"Invalid sub-scene data: {sub_scene}")
                        is_dirty_this_pass = True
                        if keyword_gen is None:
                            keyword_gen = KeywordGenerator(config) # 按需初始化
                        
                        # 重新生成整个父场景
                        self._regenerate_scene(scene, keyword_gen)
                        break # 跳出内部循环，处理下一个父场景

            if is_dirty_this_pass:
                log.info("Data was modified in this pass. Saving the corrected final_scenes.json and re-validating...")
                try:
                    with open(scenes_path, 'w', encoding='utf-8') as f:
                        json.dump(scenes_data, f, ensure_ascii=False, indent=2)
                    log.success("Successfully saved the corrected scenes file.")
                except Exception as e:
                    log.error(f"Failed to save corrected scenes file: {e}")
                    return False
            else:
                log.success("Validation complete. No issues found in final_scenes.json.")
                break # 没有更多需要修复的，退出循环

        return True

    def _regenerate_scene(self, scene: dict, keyword_gen: KeywordGenerator):
        """
        使用 KeywordGenerator 重新生成单个场景的子场景。
        该方法会就地修改传入的 scene 对象。

        Args:
            scene (dict): 需要重新生成的场景对象。
            keyword_gen (KeywordGenerator): 用于生成关键词的实例。
        """
        log.info(f"Regenerating sub-scenes for text: \"{scene['text'][:50]}...\"")
        try:
            # KeywordGenerator.generate_for_scenes 会就地修改列表中的对象
            keyword_gen.generate_for_scenes([scene])

            # 验证场景是否已成功修复
            if scene.get('scenes'):
                log.success("Successfully regenerated scene.")
            else:
                log.error("Regeneration failed to produce valid sub-scenes.")
                # 确保 scenes 字段是一个空列表以防止后续崩溃
                scene['scenes'] = []
        except Exception as e:
            log.error(f"An exception occurred during scene regeneration: {e}", exc_info=True)
            scene['scenes'] = []
