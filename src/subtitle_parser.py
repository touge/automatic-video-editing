import re
from src.logger import log

def srt_time_to_seconds(time_str: str) -> float:
    """将SRT时间格式 (HH:MM:SS,ms) 转换为秒"""
    parts = re.split(r'[:,]', time_str)
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / 1000

def parse_srt_file(srt_path: str) -> list:
    """
    解析SRT字幕文件。
    :param srt_path: SRT文件路径
    :return: 一个包含字幕段落的列表，格式与Whisper输出兼容。
    """
    # print(f"正在解析SRT文件: {srt_path}")
    segments = []
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        log.error(f"字幕文件未找到 at {srt_path}")
        return []
    
    # 使用正则表达式匹配SRT块
    srt_blocks = re.finditer(
        r'\d+\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\n|\Z)',
        content
    )
    
    for block in srt_blocks:
        segment = {
            "start": srt_time_to_seconds(block.group(1)),
            "end": srt_time_to_seconds(block.group(2)),
            "text": block.group(3).strip().replace('\n', '')
        }
        segments.append(segment)
        
    print(f"解析完成，共找到: {len(segments)} 个字幕片段。")
    return segments
