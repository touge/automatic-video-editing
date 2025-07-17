import os
import re
import json
from tqdm import tqdm
from pathlib import Path

from src.config_loader import config
from src.core.scene_splitter import SceneSplitter
from src.keyword_generator import KeywordGenerator
from src.logger import log
from src.core.task_manager import TaskManager
from src.core.fix_subtitle_timing import FixSubtitleTiming

class SceneGenerator:
    @classmethod
    def load_final_scenes(cls, task_id: str) -> list:
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
        
    @classmethod
    def save_final_scenes(cls, scenes: list, task_id: str) -> bool:
        task_manager = TaskManager(task_id)
        final_scenes_path = task_manager.get_file_path('final_scenes')
        try:
            with open(final_scenes_path, 'w', encoding='utf-8') as f:
                json.dump(scenes, f, ensure_ascii=False, indent=2)
            log.info(f"Final scenes data saved to: {final_scenes_path}")
            return True
        except Exception as e:
            log.error(f"Error saving final scenes data: {e}")
            return False

    def __init__(self, task_id: str):
        if not task_id:
            raise ValueError("A task_id must be provided.")
        
        self.task_manager = TaskManager(task_id)

    def run(self):
        log.info(f"--- Starting Scene Generation for Task ID: {self.task_manager.task_id} ---")

        final_scenes_path = self.task_manager.get_file_path('final_scenes')
        if os.path.exists(final_scenes_path):
            log.success(f"Final scenes file already exists for task {self.task_manager.task_id}. Nothing to do.")
            log.info(f"You can find the file at: {final_scenes_path}")
            return

        srt_path = self.task_manager.get_file_path('final_srt')
        if not os.path.exists(srt_path):
            # Raise an exception instead of silently returning
            raise FileNotFoundError(f"Required SRT file not found for this task: {srt_path}")

        segments = self._parse_srt()
        if not segments: return

        raw_scenes = self._split_scenes(segments)
        if not raw_scenes: return
        
        scenes_with_keywords = self._generate_keywords_for_scenes(raw_scenes)
        if not scenes_with_keywords: return

        self.save_final_scenes(scenes_with_keywords, self.task_manager.task_id)

        log.info("############################################################")
        log.success(f"Scene generation and keyword analysis complete!")
        log.info(f"Task ID: {self.task_manager.task_id}")
        log.info(f"Final scenes with keywords saved to: {final_scenes_path}")
        log.info("Next, you can manually review the final_scenes.json file or proceed to the final composition step.")
        log.info("############################################################")

    def _generate_keywords_for_scenes(self, scenes: list) -> list:
        log.info("--- Step 3: Generating keywords for each scene ---")
        keyword_gen = KeywordGenerator(config)
        scenes_iterable = tqdm(scenes, desc="Generating Keywords", unit="scene")
        
        keyword_gen.generate_for_scenes(scenes_iterable)
        
        log.success("Keyword generation complete.")
        return scenes

    def _srt_time_to_seconds(self, time_str: str) -> float:
        """将SRT时间格式 (HH:MM:SS,ms) 转换为秒"""
        parts = re.split(r'[:,]', time_str)
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / 1000

    def _parse_srt_file(self, srt_path: str) -> list:
        """
        解析SRT字幕文件。
        :param srt_path: SRT文件路径
        :return: 一个包含字幕段落的列表，格式与Whisper输出兼容。
        """
        segments = []
        try:
            with open(srt_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            log.error(f"字幕文件未找到 at {srt_path}")
            return []
        
        # print(f"正在解析SRT文件:\n-------\n {content}\n----------\n")

        # 添加人上时间误差修正
        content = FixSubtitleTiming.fix(content)
        # print(f"修正：\n{fixed_content}\n")
        # import sys; sys.exit(0)

        # 使用正则表达式匹配SRT块
        srt_blocks = re.finditer(
            r'\d+\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\n|\Z)',
            content
        )
        
        for block in srt_blocks:
            segment = {
                "start": self._srt_time_to_seconds(block.group(1)),
                "end": self._srt_time_to_seconds(block.group(2)),
                "text": block.group(3).strip().replace('\n', '')
            }
            segments.append(segment)
            
        print(f"解析完成，共找到: {len(segments)} 个字幕片段。")
        return segments

    def _parse_srt(self) -> list:
        log.info("--- Step 1: Parsing SRT file ---")
        segments_cache_path = self.task_manager.get_file_path('segments_cache')
        if os.path.exists(segments_cache_path):
            log.info(f"Found cache, loading segments from {Path(segments_cache_path).name}...")
            with open(segments_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        segments = self._parse_srt_file(self.task_manager.get_file_path('final_srt'))
        if not segments:
            log.error("Failed to parse any segments from the SRT file.")
            return []
            
        log.success(f"Parsed {len(segments)} segments, caching to {Path(segments_cache_path).name}...")
        with open(segments_cache_path, 'w', encoding='utf-8') as f:
            json.dump(segments, f, ensure_ascii=False, indent=4)
        return segments

    def _split_scenes(self, segments: list) -> list:
        log.info("--- Step 2: Splitting segments into scenes ---")

        # 获取“原始场景缓存”文件的完整路径
        scenes_raw_cache_path = self.task_manager.get_file_path('scenes_raw_cache')

        # 如果缓存文件已存在，就直接读取并返回缓存的场景列表
        if os.path.exists(scenes_raw_cache_path):
            log.info(f"Found cache, loading raw scenes from {Path(scenes_raw_cache_path).name}...")
            with open(scenes_raw_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)  # 从 JSON 文件中加载并返回场景列表

        # 实例化 SceneSplitter，用于 AI 切分；传入全局配置和当前任务 ID
        splitter = SceneSplitter(config, self.task_manager.task_id)

        # 调用 split 方法对输入片段进行场景切分
        initial_scenes = splitter.split(segments)

        # 如果切分结果为空，说明 AI 切分失败，记录错误并返回空列表
        if not initial_scenes:
            log.error("AI failed to split scenes.")  # 日志错误
            return []

        # 成功切分，记录初次切分出的场景数量
        log.success(f"AI initially split into {len(initial_scenes)} scenes.")

        # 将最终结果缓存到文件，方便下次直接加载
        log.info(f"Caching processed scenes to {Path(scenes_raw_cache_path).name}...")
        with open(scenes_raw_cache_path, 'w', encoding='utf-8') as f:
            json.dump(initial_scenes, f, ensure_ascii=False, indent=4)  # 格式化写入 JSON

        # 返回处理并缓存完成的场景列表
        return initial_scenes
