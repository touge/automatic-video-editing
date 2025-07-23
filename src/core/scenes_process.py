"""
SceneGenerator 是一个用于自动生成视频分镜及关键词的核心类，主要用于将 SRT 字幕文件处理为结构化的分镜数据，
并通过语言模型生成每个场景的关键词，支持整个内容生成流程的自动化。

功能概述：
- 支持从任务 ID 读取、缓存、保存最终分镜结构
- 利用 SceneSplitter 进行 AI 场景划分
- 调用 KeywordGenerator 为每个场景生成关键词和子镜头
- 自动解析 SRT 文件并缓存字幕片段
- 异常处理与重试机制，保障关键词生成的稳定性

使用场景：
适用于 AI 视频自动化管线中的内容结构生成阶段，特别适配分镜结构化、关键词提取、字幕文件解析等任务。

依赖模块：
- config_loader：读取全局配置
- TaskManager：管理路径、任务相关文件
- SceneSplitter：负责字幕切分为场景
- KeywordGenerator：为场景生成关键词和子镜头
- FixSubtitleTiming：修复时间重叠或对齐问题
- log：日志记录系统
"""

import os
import re
import json
from typing import Optional
from tqdm import tqdm
from pathlib import Path

# 导入配置文件、核心模块、日志模块
from src.config_loader import config
from src.core.scene_splitter import SceneSplitter
from src.keyword_generator import KeywordGenerator
from src.logger import log
from src.core.task_manager import TaskManager
from src.core.subtitle_timing_fixer import SubtitleTimingFixer  # 导入字幕时间修复工具

class SceneProcess:
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

    @classmethod
    def save_final_scenes(cls, scenes: list, task_id: str) -> bool:
        # 保存最终分镜数据到文件
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

    def __init__(self, task_id: str, style: Optional[str] = None):
        # 初始化 SceneGenerator 实例，绑定任务 ID
        if not task_id:
            raise ValueError("A task_id must be provided.")
        self.task_manager = TaskManager(task_id)
        self.style = style

    def run(self):
        # 主流程：生成分镜与关键词
        log.info(f"--- Starting Scene Generation for Task ID: {self.task_manager.task_id} ---")

        final_scenes_path = self.task_manager.get_file_path('final_scenes')
        if os.path.exists(final_scenes_path):
            log.success(f"Final scenes file already exists for task {self.task_manager.task_id}. Nothing to do.")
            log.info(f"You can find the file at: {final_scenes_path}")
            return

        srt_path = self.task_manager.get_file_path('final_srt')
        if not os.path.exists(srt_path):
            raise FileNotFoundError(f"Required SRT file not found for this task: {srt_path}")

        # 解析 SRT 文件为字幕片段
        segments = self._parse_srt()
        if not segments: return

        # 分镜逻辑处理
        raw_scenes = self._split_scenes(segments)
        if not raw_scenes: return

        # 对每个场景生成关键词
        scenes_with_keywords = self._generate_keywords_for_scenes(raw_scenes)
        if not scenes_with_keywords: return

        # 保存结果到文件
        self.save_final_scenes(scenes_with_keywords, self.task_manager.task_id)

        log.info("############################################################")
        log.success(f"Scene generation and keyword analysis complete!")
        log.info(f"Task ID: {self.task_manager.task_id}")
        log.info(f"Final scenes with keywords saved to: {final_scenes_path}")
        log.info("Next, you can manually review the final_scenes.json file or proceed to the final composition step.")
        log.info("############################################################")


    def _generate_keywords_for_scenes(self, scenes: list) -> list:
        log.info("--- Step 3: Generating keywords for each scene ---")
        keyword_gen = KeywordGenerator(config, style=self.style)
        
        # 第一次关键词生成
        log.info("Starting initial keyword generation pass...")
        scenes_iterable = tqdm(scenes, desc="Generating Keywords", unit="scene")
        keyword_gen.generate_for_scenes(scenes_iterable)
        
        # 对失败场景进行重试处理（未生成 scenes 字段的情况）
        scenes_to_retry = [s for s in scenes if not s.get('scenes')]
        
        if scenes_to_retry:
            log.warning(f"Found {len(scenes_to_retry)} scenes that failed keyword generation. Starting retry pass...")
            retry_iterable = tqdm(scenes_to_retry, desc="Retrying Keywords", unit="scene")
            keyword_gen.generate_for_scenes(retry_iterable)
            
            # 最终失败检查
            still_failed_scenes = [s for s in scenes_to_retry if not s.get('scenes')]
            if still_failed_scenes:
                failed_scene_numbers = [s.get('scene_number', 'N/A') for s in still_failed_scenes]
                log.error(f"{len(still_failed_scenes)} scenes still failed after retry: {failed_scene_numbers}. Please check LLM provider or prompts.")
        
        log.success("Keyword generation complete.")
        return scenes

    def _srt_time_to_seconds(self, time_str: str) -> float:
        """将 SRT 时间字符串 (HH:MM:SS,ms) 转换为秒数 float"""
        parts = re.split(r'[:,]', time_str)
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / 1000

    def _parse_srt_file(self, srt_path: str) -> list:
        """
        读取并解析 SRT 字幕文件，返回片段列表（包含开始时间、结束时间、文本）
        """
        segments = []
        try:
            with open(srt_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            log.error(f"字幕文件未找到 at {srt_path}")
            return []
        
        # 修复字幕时间误差（例如重叠或间隔不足）
        content = SubtitleTimingFixer.fix(content)

        # 使用正则匹配 SRT 字幕块，提取时间和文字内容
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

        # 优先使用缓存数据，加速处理流程
        if os.path.exists(segments_cache_path):
            log.info(f"Found cache, loading segments from {Path(segments_cache_path).name}...")
            with open(segments_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        # 若无缓存则解析字幕文件
        segments = self._parse_srt_file(self.task_manager.get_file_path('final_srt'))
        if not segments:
            log.error("Failed to parse any segments from the SRT file.")
            return []
            
        # 解析成功后写入缓存
        log.success(f"Parsed {len(segments)} segments, caching to {Path(segments_cache_path).name}...")
        with open(segments_cache_path, 'w', encoding='utf-8') as f:
            json.dump(segments, f, ensure_ascii=False, indent=4)
        return segments

    def _split_scenes(self, segments: list) -> list:
        log.info("--- Step 2: Splitting segments into scenes ---")
        scenes_raw_cache_path = self.task_manager.get_file_path('scenes_raw_cache')

        # 优先使用缓存数据，加速处理流程
        if os.path.exists(scenes_raw_cache_path):
            log.info(f"Found cache, loading raw scenes from {Path(scenes_raw_cache_path).name}...")
            with open(scenes_raw_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        # 实例化 SceneSplitter，用于基于字幕段落进行场景分割
        splitter = SceneSplitter(config, self.task_manager.task_id)
        initial_scenes = splitter.split(segments)

        if not initial_scenes:
            log.error("AI failed to split scenes.")
            return []

        log.success(f"AI initially split into {len(initial_scenes)} scenes.")

        # 切分结果写入缓存文件
        log.info(f"Caching processed scenes to {Path(scenes_raw_cache_path).name}...")
        with open(scenes_raw_cache_path, 'w', encoding='utf-8') as f:
            json.dump(initial_scenes, f, ensure_ascii=False, indent=4)

        return initial_scenes
