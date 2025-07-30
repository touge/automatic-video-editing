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

                # 检查并修复子场景时长
                min_duration = config.get('composition_settings.min_duration', 5)
                if self._fix_durations(scene, min_duration):
                    log.info(f"Durations fixed for scene {i+1}. Marking as dirty.")
                    is_dirty_this_pass = True

                # 检查每个子场景的字段是否缺失
                for sub_scene in scene['scenes']:
                    is_invalid_time = 'time' not in sub_scene or not isinstance(sub_scene['time'], (int, float)) or sub_scene['time'] <= 0
                    is_missing_keys = 'keys' not in sub_scene or not sub_scene['keys']
                    is_missing_text = 'source_text' not in sub_scene or not sub_scene['source_text']

                    if is_missing_keys or is_missing_text:
                        log.warning(f"Scene {i+1} contains sub-scene with missing keys or text. Triggering regeneration.")
                        log.debug(f"Invalid sub-scene data: {sub_scene}")
                        is_dirty_this_pass = True
                        if keyword_gen is None:
                            keyword_gen = KeywordGenerator(config)
                        self._regenerate_scene(scene, keyword_gen)
                        break  # 跳出内部循环，处理下一个父场景
                    
                    if is_invalid_time:
                        log.warning(f"Scene {i+1} contains sub-scene with invalid time. Triggering regeneration.")
                        log.debug(f"Invalid sub-scene data: {sub_scene}")
                        is_dirty_this_pass = True
                        if keyword_gen is None:
                            keyword_gen = KeywordGenerator(config)
                        self._regenerate_scene(scene, keyword_gen)
                        break

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

        # 再次保存，因为时长修复可能在循环之后发生
        if any(self._fix_durations(s, config.get('composition_settings.min_duration', 5)) for s in scenes_data):
            log.info("Final duration corrections applied. Saving file one last time.")
            try:
                with open(scenes_path, 'w', encoding='utf-8') as f:
                    json.dump(scenes_data, f, ensure_ascii=False, indent=2)
                log.success("Successfully saved the final corrected scenes file.")
            except Exception as e:
                log.error(f"Failed to save final corrected scenes file: {e}")
                return False

        return True

    def _fix_durations(self, scene: dict, min_duration: float) -> bool:
        """
        检查并修复单个父场景中子场景的时长。
        如果子场景时长小于 min_duration，则会尝试合并。
        返回 True 如果场景被修改，否则返回 False。
        """
        if not scene.get('scenes'):
            return False

        is_modified = False
        
        # 过滤掉时长过短的场景，并准备合并
        valid_scenes = []
        scenes_to_merge = list(scene['scenes'])

        while scenes_to_merge:
            current_scene = scenes_to_merge.pop(0)
            
            # 如果当前场景时长已经满足要求
            if current_scene['time'] >= min_duration:
                valid_scenes.append(current_scene)
                continue

            is_modified = True
            # 如果当前场景时长不足，且后面还有场景可以合并
            if scenes_to_merge:
                next_scene = scenes_to_merge[0]
                log.warning(f"Merging short scene (duration: {current_scene['time']}) with next scene (duration: {next_scene['time']}).")
                
                # 合并关键词和文本
                next_scene['keys'] = list(set(current_scene.get('keys', []) + next_scene.get('keys', [])))
                next_scene['zh_keys'] = list(set(current_scene.get('zh_keys', []) + next_scene.get('zh_keys', [])))
                next_scene['source_text'] = (current_scene.get('source_text', '') + " " + next_scene.get('source_text', '')).strip()
                next_scene['time'] += current_scene['time']
            else:
                # 如果是最后一个场景且时长不足，则尝试与前一个合并
                if valid_scenes:
                    log.warning(f"Merging last short scene (duration: {current_scene['time']}) with previous scene.")
                    last_valid_scene = valid_scenes[-1]
                    last_valid_scene['keys'] = list(set(last_valid_scene.get('keys', []) + current_scene.get('keys', [])))
                    last_valid_scene['zh_keys'] = list(set(last_valid_scene.get('zh_keys', []) + current_scene.get('zh_keys', [])))
                    last_valid_scene['source_text'] = (last_valid_scene.get('source_text', '') + " " + current_scene.get('source_text', '')).strip()
                    last_valid_scene['time'] += current_scene['time']
                else:
                    # 如果只有一个场景且时长不足，则强制设置为父场景时长
                    log.warning(f"Single scene with insufficient duration. Setting to parent duration: {scene['duration']}.")
                    current_scene['time'] = scene['duration']
                    valid_scenes.append(current_scene)

        if is_modified:
            scene['scenes'] = valid_scenes
            # 重新分配总时长，确保加起来等于父场景时长
            self._redistribute_total_duration(scene)

        return is_modified

    def _redistribute_total_duration(self, scene: dict):
        """
        重新计算并分配一个父场景下所有子场景的总时长，确保其总和等于父场景的 `duration`。
        """
        if not scene.get('scenes'):
            return

        sub_scenes = scene['scenes']
        total_sub_duration = sum(s['time'] for s in sub_scenes)
        parent_duration = scene['duration']

        if abs(total_sub_duration - parent_duration) > 0.01: # 允许小的浮点误差
            log.warning(f"Total duration of sub-scenes ({total_sub_duration}) does not match parent duration ({parent_duration}). Redistributing.")
            
            # 按比例重新分配
            ratio = parent_duration / total_sub_duration if total_sub_duration > 0 else 0
            for sub_scene in sub_scenes:
                sub_scene['time'] = round(sub_scene['time'] * ratio, 2)
            
            # 处理可能的舍入误差，将其加到最后一个场景
            new_total = sum(s['time'] for s in sub_scenes)
            rounding_error = parent_duration - new_total
            if sub_scenes and abs(rounding_error) > 0.001:
                sub_scenes[-1]['time'] = round(sub_scenes[-1]['time'] + rounding_error, 2)


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
