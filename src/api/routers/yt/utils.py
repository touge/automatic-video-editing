import re

def get_youtube_url(video_input: str) -> str:
    """
    根据输入是 video_id 还是完整的 URL，返回一个完整的 YouTube URL。
    """
    if video_input.startswith('http://') or video_input.startswith('https://'):
        return video_input
    else:
        return f"https://www.youtube.com/watch?v={video_input}"

def get_video_id(video_input: str) -> str:
    """
    从 YouTube URL 或 video_id 字符串中提取 video_id。
    """
    match = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})(?:&|\?)?.*', video_input)
    if match:
        return match.group(1)
    # 如果没有匹配到，假定输入本身就是 video_id
    return video_input

def _srt_time_to_seconds(time_str: str) -> float:
    try:
        h_str, m_str, s_ms_str = time_str.split(':')
        s_str, ms_str = s_ms_str.split(',')
        return int(h_str) * 3600 + int(m_str) * 60 + int(s_str) + int(ms_str) / 1000
    except (ValueError, IndexError):
        return 0.0

def parse_srt_file(path: str) -> list:
    segments_list = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        return []
    
    srt_blocks = re.finditer(
        r'\d+\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\n|\Z)',
        content
    )
    
    for block in srt_blocks:
        start_time = _srt_time_to_seconds(block.group(1))
        end_time = _srt_time_to_seconds(block.group(2))
        text = block.group(3).strip().replace('\n', ' ')
        
        class Segment:
            def __init__(self, start, end, text):
                self.start = start
                self.end = end
                self.text = text
        
        segments_list.append(Segment(start=start_time, end=end_time, text=text))
    return segments_list
