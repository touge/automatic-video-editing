import json
from collections import deque
from src.core.task_manager import TaskManager
from src.keyword_generator import KeywordGenerator
from src.config_loader import config
from src.logger import log

class SceneValidator:
    """
    负责验证和修复 final_scenes.json 文件中的数据完整性和正确性。
    通过迭代验证和修复，确保数据结构的健壮性。
    """

    def __init__(self, task_id: str):
        """
        初始化验证器。

        Args:
            task_id (str): 当前任务的 ID。
        """
        self.task_id = task_id
        self.task_manager = TaskManager(task_id)
        self.min_duration = config.get('composition_settings.min_duration', 5)
        self.max_scene_fix_retries = config.get('validation_settings.max_scene_fix_retries', 10) 

    def validate_and_fix(self) -> bool:
        """
        加载、验证并修复 final_scenes.json 文件。
        该方法将逐个主场景进行修复，直到其内部所有子场景都符合要求。
        所有修复操作都在内存中进行，最后一次性写回文件。
        
        Returns:
            bool: 如果所有问题成功修复并验证通过则返回True，否则返回False。
        """
        log.info(f"Starting validation for task '{self.task_id}'...")
        scenes_path = self.task_manager.get_file_path('final_scenes')
        
        try:
            with open(scenes_path, 'r', encoding='utf-8') as f:
                scenes_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.error(f"Could not read or parse final_scenes.json: {e}")
            return False

        if not scenes_data:
            log.info("final_scenes.json is empty. No validation needed.")
            return True

        keyword_gen = None
        overall_modified = False 
        
        # 使用 deque 便于在迭代中移除元素和添加元素到头部/尾部
        # 这里为了处理第一个场景合并到下一个场景的逻辑，我们需要对原始列表直接进行操作
        # 或者维护一个 new_scenes_data 列表来构建最终结果
        new_scenes_data = [] # 用于构建最终的场景列表
        
        i = 0 # 手动索引，因为列表长度会变化
        while i < len(scenes_data):
            current_main_scene = scenes_data[i]
            
            log.info(f"Processing main scene {i + 1} (start: {current_main_scene.get('start', 0):.2f}s, end: {current_main_scene.get('end', 0):.2f}s)...")
            
            scene_was_fixed_in_pass = False 
            current_scene_fix_retry = 0 

            # **【核心修改点1：处理第一个场景且时长不足的情况】**
            # 如果是第一个主场景 (i == 0)，并且只有一个子场景且时长不足，且后面还有场景
            if (i == 0 and 
                len(current_main_scene.get('scenes', [])) == 1 and
                current_main_scene.get('duration', 0) < self.min_duration and
                len(scenes_data) > 1): # 确保后面至少有一个场景可以合并
                
                log.warning(f"First main scene ({i + 1}) has single sub-scene and short duration ({current_main_scene.get('duration', 0):.2f}s). Attempting to merge with the next main scene.")
                
                next_main_scene = scenes_data[i+1] # 获取下一个主场景

                # 调用新的合并方法：将 current_main_scene 合并到 next_main_scene
                self._merge_main_scenes_forward(current_main_scene, next_main_scene)
                
                # 移除当前主场景 (因为它已被合并到下一个)
                scenes_data.pop(i) 
                # next_main_scene 保持在原位 (i+1 现在变为 i)，将在下一轮循环被处理
                # 所以这里不需要 i++，因为它会指向新的当前场景 (合并后的原 next_main_scene)
                overall_modified = True
                continue # 当前场景已合并并移除，继续下一轮循环从当前位置开始处理
            
            # **【核心修改点2：处理非第一个主场景且时长不足但可合并到前一个的情况】**
            # 如果当前主场景只有一个子场景，并且时长小于 min_duration，尝试合并到前一个主场景
            # 只有在 i > 0 时才能合并到前一个
            elif (len(current_main_scene.get('scenes', [])) == 1 and 
                  current_main_scene.get('duration', 0) < self.min_duration and
                  i > 0): # 确保前面有场景可以合并
                
                log.warning(f"Main scene {i + 1} has single sub-scene and short duration ({current_main_scene.get('duration', 0):.2f}s). Attempting to merge with previous main scene.")
                
                previous_main_scene = scenes_data[i-1] # 获取前一个主场景
                
                self._merge_main_scenes_backward(previous_main_scene, current_main_scene)
                
                # 移除当前主场景 (因为它已被合并到上一个)
                scenes_data.pop(i) 
                # 由于移除了当前场景，i 保持不变，下一轮循环会处理原来 i+1 位置的场景
                overall_modified = True
                continue # 当前场景已合并并移除，继续下一轮循环从当前位置开始处理


            # 针对当前主场景进行循环修复，直到它稳定或达到最大尝试次数
            while current_scene_fix_retry < self.max_scene_fix_retries:
                current_scene_fix_retry += 1
                log.debug(f"Attempting to fix main scene {i + 1}, retry {current_scene_fix_retry}/{self.max_scene_fix_retries}")
                
                if self._is_scene_structure_invalid(current_main_scene):
                    log.warning(f"Main scene {i + 1} structure is invalid. Triggering regeneration of its sub-scenes.")
                    scene_was_fixed_in_pass = True
                    if keyword_gen is None:
                        keyword_gen = KeywordGenerator(config)
                    self._regenerate_scene(current_main_scene, keyword_gen)
                    continue 
                
                if self._fix_durations(current_main_scene, self.min_duration):
                    log.info(f"Durations fixed for main scene {i + 1}. Marking as modified.")
                    scene_was_fixed_in_pass = True
                    continue
                
                break 
            
            if current_scene_fix_retry >= self.max_scene_fix_retries:
                log.error(f"Exceeded max fix retries ({self.max_scene_fix_retries}) for main scene {i + 1}. This scene might still have issues.")
            
            if scene_was_fixed_in_pass:
                overall_modified = True 
            
            # 如果当前主场景没有被合并和移除，则移到下一个
            i += 1 

        # 所有主场景处理完毕后，一次性写回文件
        # scenes_data 已经是在内存中直接修改和移除后的最终列表
        if overall_modified:
            log.info("Overall data was modified. Saving the final corrected final_scenes.json...")
            try:
                with open(scenes_path, 'w', encoding='utf-8') as f:
                    json.dump(scenes_data, f, ensure_ascii=False, indent=2)
                log.success("Successfully saved the final corrected scenes file.")
            except Exception as e:
                log.error(f"Failed to save final corrected scenes file: {e}")
                return False
        else:
            log.success("No issues found in final_scenes.json after all checks. No save needed.")

        return True 

    def _is_scene_structure_invalid(self, scene: dict) -> bool:
        """检查一个主场景及其子场景的结构是否无效。"""
        if not scene.get('scenes') or not isinstance(scene['scenes'], list):
            log.debug(f"Scene missing 'scenes' list or not a list for scene text: '{scene.get('text', '')[:30]}...'")
            return True
        
        for sub_scene_idx, sub_scene in enumerate(scene['scenes']):
            is_invalid_time = 'time' not in sub_scene or not isinstance(sub_scene['time'], (int, float)) or sub_scene['time'] <= 0
            is_missing_content = not sub_scene.get('keys') or not sub_scene.get('source_text')
            
            if is_invalid_time or is_missing_content:
                log.debug(f"Invalid sub-scene data found at index {sub_scene_idx} for scene text: '{scene.get('text', '')[:30]}...'. Sub-scene: {sub_scene}")
                return True
        return False

    def _merge_main_scenes_backward(self, target_main_scene: dict, source_main_scene: dict):
        """
        合并两个主场景：将 source_main_scene 的内容合并到 target_main_scene (前一个场景)。
        同时更新 target_main_scene 的 duration 和 end 时间。
        """
        log.info(f"Merging main scene (text: '{source_main_scene.get('text', '')[:30]}...') into previous main scene (text: '{target_main_scene.get('text', '')[:30]}...').")
        
        # 合并文本
        target_main_scene['text'] = (target_main_scene.get('text', '') + " " + source_main_scene.get('text', '')).strip()

        # 合并子场景列表
        if 'scenes' not in target_main_scene:
            target_main_scene['scenes'] = []
        target_main_scene['scenes'].extend(source_main_scene.get('scenes', []))

        # 更新 duration 和 end
        # 新的 duration 是两个场景 duration 的总和
        target_main_scene['duration'] = round(target_main_scene.get('duration', 0) + source_main_scene.get('duration', 0), 3)
        # 新的 end 是被合并场景的 end
        target_main_scene['end'] = source_main_scene.get('end', target_main_scene.get('end', 0))

        log.success(f"Main scenes merged backward. New duration: {target_main_scene['duration']:.2f}s, New end: {target_main_scene['end']:.2f}s.")

    def _merge_main_scenes_forward(self, source_main_scene: dict, target_main_scene: dict):
        """
        合并两个主场景：将 source_main_scene (当前短场景) 的内容合并到 target_main_scene (下一个场景)。
        同时更新 target_main_scene 的 start 和 duration 时间。
        """
        log.info(f"Merging short main scene (text: '{source_main_scene.get('text', '')[:30]}...') into next main scene (text: '{target_main_scene.get('text', '')[:30]}...').")
        
        # 更新下一个场景的 start 时间为当前场景的 start
        target_main_scene['start'] = source_main_scene.get('start', target_main_scene.get('start', 0))
        
        # 合并文本
        target_main_scene['text'] = (source_main_scene.get('text', '') + " " + target_main_scene.get('text', '')).strip()

        # 合并子场景列表 (将当前场景的子场景放在前面)
        if 'scenes' not in target_main_scene:
            target_main_scene['scenes'] = []
        target_main_scene['scenes'] = source_main_scene.get('scenes', []) + target_main_scene['scenes']


        # 更新 duration
        # 新的 duration 是两个场景 duration 的总和
        target_main_scene['duration'] = round(source_main_scene.get('duration', 0) + target_main_scene.get('duration', 0), 3)
        # end 时间不变，因为它是由下一个场景决定的

        log.success(f"Main scenes merged forward. New start: {target_main_scene['start']:.2f}s, New duration: {target_main_scene['duration']:.2f}s.")


    def _merge_sub_scenes(self, target_scene: dict, source_scene: dict):
        """辅助函数，用于合并两个子场景的数据。"""
        target_scene['keys'] = list(set(target_scene.get('keys', []) + source_scene.get('keys', [])))
        target_scene['zh_keys'] = list(set(target_scene.get('zh_keys', []) + source_scene.get('zh_keys', [])))
        target_scene['source_text'] = (target_scene.get('source_text', '') + " " + source_scene.get('source_text', '')).strip()
        target_scene['time'] += source_scene.get('time', 0)

    def _fix_durations(self, scene: dict, min_duration: float) -> bool:
        """
        检查并修复子场景时长，通过合并来消除过短的场景。
        返回 True 如果场景被修改，否则返回 False。
        """
        if not scene.get('scenes'):
            return False

        was_modified = False
        scenes_to_process = deque(scene.get('scenes', []))
        fixed_scenes = []

        while scenes_to_process:
            current_sub_scene = scenes_to_process.popleft() 

            if current_sub_scene.get('time', 0) >= min_duration:
                fixed_scenes.append(current_sub_scene)
                continue
            
            was_modified = True
            
            if scenes_to_process:
                next_sub_scene = scenes_to_process.popleft() 
                log.warning(f"Merging short sub-scene (duration: {current_sub_scene.get('time', 0):.2f}s) with next sub-scene (duration: {next_sub_scene.get('time', 0):.2f}s). Parent text: '{scene.get('text', '')[:30]}...'")
                self._merge_sub_scenes(next_sub_scene, current_sub_scene)
                scenes_to_process.appendleft(next_sub_scene) 
            elif fixed_scenes:
                log.warning(f"Merging last short sub-scene (duration: {current_sub_scene.get('time', 0):.2f}s) into previous sub-scene. Parent text: '{scene.get('text', '')[:30]}...'")
                last_valid_scene = fixed_scenes[-1]
                self._merge_sub_scenes(last_valid_scene, current_sub_scene)
            else:
                # 这种情况下，父场景只包含一个子场景，且该子场景时长不足。
                # 由于前面已经增加了主场景合并逻辑，这里作为最后防线，如果仍未被合并，则强制拉长。
                target_duration = scene.get('duration', min_duration) 
                log.warning(f"Single remaining sub-scene with insufficient duration after merging attempts. Forcing to parent duration: {target_duration:.2f}s. Parent text: '{scene.get('text', '')[:30]}...'")
                current_sub_scene['time'] = target_duration
                fixed_scenes.append(current_sub_scene)

        if was_modified:
            scene['scenes'] = fixed_scenes
            self._redistribute_total_duration(scene)
        
        return was_modified

    def _redistribute_total_duration(self, scene: dict):
        """按比例重新分配子场景时长，确保其总和等于父场景的duration。"""
        if not scene.get('scenes'):
            return

        sub_scenes = scene['scenes']
        parent_duration = scene.get('duration', 0) 
        if parent_duration == 0: 
            log.warning(f"Parent scene duration is 0 for scene text: '{scene.get('text', '')[:30]}...', cannot redistribute sub-scene durations.")
            return

        total_sub_duration = sum(s.get('time', 0) for s in sub_scenes)
        if total_sub_duration == 0:
            log.warning(f"Total sub-scene duration is 0 for scene text: '{scene.get('text', '')[:30]}...', cannot redistribute.")
            return

        if abs(total_sub_duration - parent_duration) > 0.01:
            log.warning(f"Sub-scenes total duration ({total_sub_duration:.2f}s) differs from parent ({parent_duration:.2f}s) for scene text: '{scene.get('text', '')[:30]}...'. Redistributing.")
            
            ratio = parent_duration / total_sub_duration
            
            for sub_scene in sub_scenes:
                sub_scene['time'] = round(sub_scene.get('time', 0) * ratio, 2)
            
            new_total = sum(s.get('time', 0) for s in sub_scenes)
            rounding_error = parent_duration - new_total
            if sub_scenes and abs(rounding_error) > 0.001:
                sub_scenes[-1]['time'] = round(sub_scenes[-1].get('time', 0) + rounding_error, 2)

    def _regenerate_scene(self, scene: dict, keyword_gen: KeywordGenerator):
        """使用KeywordGenerator重新生成单个场景的子场景（就地修改）。"""
        scene_text = scene.get('text', '') 
        log.info(f"Regenerating sub-scenes for text: \"{scene_text[:50]}...\" (Parent duration: {scene.get('duration', 0):.2f}s)")
        try:
            keyword_gen.generate_for_scenes([scene])

            if scene.get('scenes'):
                log.success("Successfully regenerated scene.")
            else:
                log.error(f"Regeneration failed: No valid sub-scenes were produced for scene text: '{scene_text[:50]}...'.")
                scene['scenes'] = [] 
        except Exception as e:
            log.error(f"An exception occurred during scene regeneration for scene text: '{scene_text[:50]}...': {e}", exc_info=True)
            scene['scenes'] = []