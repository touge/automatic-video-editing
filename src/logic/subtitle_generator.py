# 导入必要的库和模块
import os  # 文件和路径操作
import json  # 处理JSON格式数据
import pickle  # 对象序列化和反序列化
from tqdm import tqdm  # 显示进度条
from typing import List, Dict  # 类型注解

# 导入项目内自定义模块
from src.logger import log  # 日志记录模块
from src.config_loader import config  # 配置加载模块

from src.core.task_manager import TaskManager  # 任务管理器
from src.core.model_loader import ModelLoader  # 模型加载器
from src.core.text import TextProcessor  # 文本处理器
from src.core.search import Searcher  # 文本音频匹配模块
from src.core.audio_transcriber import AudioTranscriber  # 音频处理器

from src.utils import add_line_breaks_after_punctuation  # 文本断句工具

# 定义字幕处理类
class SubtitleGenerator:
    # 构造方法，初始化任务ID与文档路径
    def __init__(self, task_id: str, doc_file: str):
        if not task_id or not doc_file:  # 参数有效性校验
            raise ValueError("task_id and doc_file must be provided.")
        if not os.path.exists(doc_file):  # 检查文档文件是否存在
            raise FileNotFoundError(f"Document file not found at '{doc_file}'")
        
        self.task_manager = TaskManager(task_id)  # 初始化任务管理器
        self.doc_file = doc_file  # 存储文档路径

    # 运行字幕生成主流程
    def run(self) -> str:
        log.info(f"--- Starting Subtitle Generation for Task ID: {self.task_manager.task_id} ---")
        try:
            final_audio_path = self.task_manager.get_file_path('final_audio')  # 获取音频路径
            if not os.path.exists(final_audio_path):  # 检查音频是否存在
                raise FileNotFoundError(f"Final audio file not found for this task: {final_audio_path}")
            
            self._generate_subtitles(final_audio_path)  # 执行字幕生成流程
            
            srt_path = self.task_manager.get_file_path('final_srt')  # 获取SRT文件路径
            log.success(f"Subtitle generation completed successfully. SRT file at: {srt_path}")
            return srt_path  # 返回结果路径
        except Exception as e:
            log.error(f"Subtitle generation pipeline failed: {e}", exc_info=True)
            raise  # 抛出异常供外部处理

    # 将最终音频保存到任务目录
    def save_final_audio(self, audio_content: bytes):
        final_audio_path = self.task_manager.get_file_path('final_audio')  # 获取保存路径
        with open(final_audio_path, 'wb') as f:
            f.write(audio_content)  # 写入音频内容
        log.info(f"Saved provided audio content to {final_audio_path}")

    # 字幕生成核心流程
    def _generate_subtitles(self, final_audio_path: str):
        try:
            log.info("\n--- Initializing models for subtitle generation ---")

            model_loader = ModelLoader(config)  # 初始化模型加载器
            audio_transcriber = AudioTranscriber(model_loader)  # 初始化音频处理器
            text_processor = TextProcessor(model_loader)  # 初始化文本处理器
            searcher = Searcher(model_loader, text_processor)  # 初始化搜索匹配器

            log.success("Core components for subtitling initialized.")
            
            # 拆分文本、音频转录、文本音频对齐、生成SRT文件
            sentences = self._split_text_into_sentences(
                self.task_manager.get_file_path('original_doc'),
                self.task_manager.get_file_path('sentences')
            )
            whisper_segments = self._transcribe_audio(
                audio_transcriber,
                final_audio_path,
                self.task_manager.get_file_path('whisper_cache')
            )
            aligned_data = self._align_text_to_audio(
                searcher,
                sentences,
                whisper_segments,
                self.task_manager.get_file_path('alignment_cache')
            )
            self._create_srt_from_alignment(
                aligned_data,
                self.task_manager.get_file_path('final_srt')
            )
        except Exception as e:
            log.error(f"An error occurred during subtitle generation: {e}", exc_info=True)
            raise

    # 拆分原始文本为句子，并根据长度规则合并/拆分
    def _split_text_into_sentences(self, original_text_path: str, sentences_output_path: str) -> List[str]:
        log.info("\n--- Step 3.1: Splitting text into sentences for alignment ---")  # 日志：开始拆分文本为句子

        if os.path.exists(sentences_output_path):  # 如果缓存文件已存在，直接读取返回
            log.info(f"Found existing sentences cache: {sentences_output_path}")  # 日志：发现已存在的缓存
            with open(sentences_output_path, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f]  # 逐行读取并去除首尾空格，返回列表

        with open(original_text_path, 'r', encoding='utf-8') as f:
            content = f.read()  # 读取原始文档内容为字符串

        raw_sentences = TextProcessor.split_and_clean_sentences(content)  # 初步使用分句工具拆分文本为句子列表
        processed_sentences = []  # 存放最终处理后的句子
        i = 0  # 当前处理索引

        while i < len(raw_sentences):
            current = raw_sentences[i].strip()  # 当前句子去除空格
            # 条件1：当前句子≤5个字，且下一句存在且≤15个字，则进行合并，空格连接
            if len(current) <= 5 and i + 1 < len(raw_sentences):
                next_line = raw_sentences[i + 1].strip()  # 获取下一句
                if len(next_line) <= 15:
                    merged = current + ' ' + next_line  # 用空格连接当前和下一句
                    processed_sentences.append(merged)  # 添加合并结果
                    i += 2  # 跳过当前和下一句
                    continue  # 继续循环处理下一个
            # 条件2：当前句子长度超过20字，进行语义切分（至少5字）
            elif len(current) > 20:
                splits = TextProcessor.smart_split(current, min_len=5, max_len=20)  # 调用智能拆分方法
                processed_sentences.extend(splits)  # 添加拆分结果到列表
                i += 1  # 处理下一个句子
                continue
            # 默认情况：当前句子长度适中，直接添加
            processed_sentences.append(current)
            i += 1  # 移动到下一个句子

        # 将最终处理好的句子写入缓存文件
        with open(sentences_output_path, 'w', encoding='utf-8') as f:
            for sentence in processed_sentences:
                f.write(sentence + '\n')  # 每行写入一个句子

        log.success(f"Processed {len(processed_sentences)} sentences and saved to {sentences_output_path}")  # 日志：处理完成
        return processed_sentences  # 返回处理后的句子列表

    # 使用Whisper模型转录音频
    def _transcribe_audio(self, audio_transcriber: AudioTranscriber, audio_path: str, whisper_cache_path: str) -> List[Dict]:
        log.info("\n--- Step 3.2: Transcribing audio with Whisper ---")

        if os.path.exists(whisper_cache_path):  # 若转录结果已缓存则读取
            log.info(f"Found existing Whisper cache: {whisper_cache_path}")
            with open(whisper_cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
            
        log.info(f"Running transcription for {audio_path}...")  # 开始音频转录

        _, whisper_segments, _ = audio_transcriber.transcribe(audio_path)  # 执行转录
        if not whisper_segments:
            raise RuntimeError("Transcription failed, no segments returned.")  # 转录失败处理
        with open(whisper_cache_path, 'w', encoding='utf-8') as f:
            json.dump(whisper_segments, f, ensure_ascii=False, indent=4)  # 保存转录结果
        log.success(f"Transcription saved to {whisper_cache_path}")
        return whisper_segments

    # 将文本句子与音频转录结果进行对齐
    def _align_text_to_audio(self, searcher: Searcher, sentences: List[str], whisper_segments: List[Dict], alignment_cache_path: str) -> List[Dict]:
        log.info("\n--- Step 3.3: Aligning text to audio ---")

        if os.path.exists(alignment_cache_path):  # 若对齐结果已缓存则读取
            log.info(f"Found existing alignment cache: {alignment_cache_path}")
            with open(alignment_cache_path, 'rb') as f:
                return pickle.load(f)

        log.info("Running linear alignment...")  # 开始对齐

        all_whisper_words = [word for segment in whisper_segments for word in segment.get('words', [])]  # 提取所有词
        aligned_data, _ = searcher.linear_align(sentences, all_whisper_words)  # 执行线性对齐
        with open(alignment_cache_path, 'wb') as f:
            pickle.dump(aligned_data, f)  # 缓存对齐结果
        log.success(f"Alignment data saved to {alignment_cache_path}")
        return aligned_data

    # 根据对齐结果生成SRT字幕文件
    def _create_srt_from_alignment(self, aligned_data: List[Dict], srt_output_path: str):
        log.info("--- Step 3.4: Generating SRT file ---")

        aligned_data.sort(key=lambda x: x['start'])  # 按开始时间排序
        punctuations_for_linebreak = ['！', '？', '。', '…']  # 断句符号集合
        with open(srt_output_path, 'w', encoding='utf-8') as f:
            for i, entry in enumerate(aligned_data):
                start_time = TextProcessor.format_time(entry['start'])  # 格式化开始时间
                end_time = TextProcessor.format_time(entry['end'])  # 格式化结束时间
                text = entry['text']  # 提取文本内容
                processed_text = add_line_breaks_after_punctuation(text, punctuations_for_linebreak)  # 断句处理
                f.write(f"{i + 1}\n")  # 写入字幕编号
                f.write(f"{start_time} --> {end_time}\n")  # 写入时间轴
                f.write(f"{processed_text.strip()}\n\n")  # 写入字幕文本
        log.success(f"Final SRT file generated at: {srt_output_path}")
