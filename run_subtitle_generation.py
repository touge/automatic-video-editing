# -*- coding: utf-8 -*-
import os
from src.core.whisper_subtitle_generator import WhisperSubtitleGenerator

def run_generation():
    """
    运行字幕生成。
    """
    # 实例化 Whisper 字幕生成器
    # 可选模型: "tiny", "base", "small", "medium", "large"
    generator = WhisperSubtitleGenerator(model_name="medium", models_dir="models")

    # 定义输入文件路径
    # 请将这里的路径替换为您的实际文件路径
    audio_file = os.path.join("input", "1.wav")
    output_file = os.path.join("output", "1_whisper.srt")
    
    # 生成字幕，并设置语言、最小和最大行长度
    try:
        generator.generate(
            audio_path=audio_file,
            output_path=output_file,
            language="zh",
            min_line_length=8,
            max_line_length=15
        )
    except FileNotFoundError as e:
        print(f"错误: {e}")
    except RuntimeError as e:
        print(f"运行时错误: {e}")

if __name__ == "__main__":
    run_generation()
