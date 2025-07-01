import ffmpeg
import os

def extract_audio(video_path: str, output_audio_path: str) -> str:
    """
    从视频中提取音频。
    :param video_path: 输入视频文件路径
    :param output_audio_path: 输出音频文件路径
    :return: 输出音频文件的路径
    """
    print(f"正在从 {video_path} 提取音频...")
    (ffmpeg.input(video_path)
           .output(output_audio_path, acodec='pcm_s16le', ar='16000', ac=1)
           .run(overwrite_output=True, quiet=True))
    print(f"音频已保存到 {output_audio_path}")
    return output_audio_path

