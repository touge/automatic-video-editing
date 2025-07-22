"""
audio_transcriber.py

音频转录模块，负责将音频文件转换为文本并提取时间戳信息，支持词级标注。
该模块依赖 Whisper 模型，封装为 AudioTranscriber 类，提供结构化转录输出，
可用于字幕生成、语音分析等任务，是 SubtitleProcessor 的辅助组件。

依赖组件：
- ModelLoader：用于加载 Whisper 模型实例
- tqdm：用于展示转录进度条
- logger：记录处理日志
"""

import os  # 操作系统模块，用于路径处理、文件检查等功能
from tqdm import tqdm  # 用于显示进度条，提升用户体验
from typing import List, Dict  # 类型注解，提升代码可读性和可维护性

from src.logger import log  # 引入日志工具，方便记录运行信息与错误
from src.core.model_loader import ModelLoader  # 引入模型加载器，用于获取 Whisper 模型

class AudioTranscriber:
    """
    音频处理器类，主要负责音频转录
    是 SubtitleProcessor 的辅助类
    """
    def __init__(self, model_loader: ModelLoader):
        self.whisper_model = model_loader.get_whisper_model()  # 加载 Whisper 模型并保存为实例变量

    def transcribe(self, audio_file: str):
        if not self.whisper_model:  # 如果模型没有成功加载
            log.error("Whisper model not available for transcription.")  # 记录错误日志
            return None, None, None  # 返回空结果
        log.info(f"Transcribing audio file: {audio_file} (this may take a while)...")  # 日志提示开始处理音频文件
        # 调用模型进行转录，启用 beam search 和词级时间戳
        segments, info = self.whisper_model.transcribe(audio_file, beam_size=5, word_timestamps=True)
        full_text = ""  # 初始化全文字符串
        segments_info = []  # 初始化片段信息列表
        # 遍历所有转录片段，显示进度条
        for segment in tqdm(segments, desc="Processing transcription segments"):
            full_text += segment.text  # 拼接每段文本到全文
            words_info = []  # 当前片段的词信息列表
            if segment.words:  # 如果该片段包含词级信息
                for word in segment.words:  # 遍历所有词
                    # 添加词的文本及起止时间到词信息列表
                    words_info.append({"word": word.word, "start": word.start, "end": word.end})
            # 组装当前片段的结构化信息并添加到片段列表中
            segments_info.append({"start": segment.start, "end": segment.end, "text": segment.text, "words": words_info})
        log.info("Audio transcription complete.")  # 日志提示转录完成
        # 返回：全文文本、结构化片段信息、附加转录元数据
        return full_text, segments_info, info
