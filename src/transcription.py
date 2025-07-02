import whisper
import os
from src.logger import log
from src.color_utils import (
    print_colored,
    print_error,
    print_warning,
    print_success,
    print_info,
)
def transcribe_audio(audio_path: str, model_name: str = "base") -> list:
    """
    使用Whisper将音频转换为带时间戳的字幕段落。
    :param audio_path: 音频文件路径
    :param model_name: Whisper模型名称 (e.g., "tiny", "base", "small", "medium", "large")
    :return: 一个包含字幕段落的列表，每个段落是一个字典
    """
    print_info(f"正在加载Whisper模型 '{model_name}'...")
    model = whisper.load_model(model_name)
    print_info(f"正在转录音频: {audio_path}...")
    result = model.transcribe(audio_path, verbose=False)
    print_info("转录完成。")
    return result["segments"]
