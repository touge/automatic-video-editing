import yaml
import json
import os
import sys
import re # Import the 're' module
import subprocess # For running ffprobe
import json # For parsing ffprobe output
from src.logger import log
from src.providers.llm import LlmManager
from typing import List, Dict, Optional

from typing import List, Dict

def adjust_subtitle_timings(aligned_data: List[Dict], gap_tolerance_ms: int = 0) -> List[Dict]:
    """
    自动修正字幕时间对齐：
    如果当前句的结束时间与下一句开始时间之间的差值大于 `gap_tolerance_ms` 毫秒，
    则强制将结束时间设置为下一句开始时间。
    最后一条字幕保持原始结束时间。

    参数：
    - aligned_data: 字幕段落列表，每个包含 'start'、'end'、'text'
    - gap_tolerance_ms: 差值容差（单位：毫秒），默认为 0，即任意差值都修复
    """
    if not isinstance(aligned_data, list):
        raise TypeError(f"Expected list of dicts, got {type(aligned_data).__name__}")

    filtered_data = [
        entry for entry in aligned_data
        if isinstance(entry, dict) and 'start' in entry and 'end' in entry and 'text' in entry
    ]

    filtered_data.sort(key=lambda x: x['start'])

    adjusted = []
    for i, entry in enumerate(filtered_data):
        corrected = entry.copy()

        if i < len(filtered_data) - 1:
            next_start = filtered_data[i + 1]['start']
            time_gap_ms = abs(corrected['end'] - next_start) * 1000

            if time_gap_ms > gap_tolerance_ms:
                corrected['end'] = next_start  # 超过容差才修正

        adjusted.append(corrected)

    return adjusted

def check_llm_providers(config: dict):
    """
    检查所有在config.yaml中启用的LLM提供者是否可用。
    """
    log.info("正在检查所有已启用的LLM提供者...")
    
    try:
        llm_manager = LlmManager(config)
        
        if not llm_manager.providers:
            log.error("错误: 未能加载任何LLM提供者。")
            log.error("请检查config.yaml中的'llm_providers'配置以及服务连接。程序将中止。")
            sys.exit(1) # 确保在没有提供者时退出

        log.success(f"成功加载 {len(llm_manager.providers)} 个LLM提供者: {list(llm_manager.providers.keys())}")

        if not llm_manager.default:
            log.warning("警告: 默认的LLM提供者未能加载，但有其他可用的提供者。")
            log.warning(f"程序将使用 '{llm_manager.default_provider_name}' 作为备用。")
        else:
            log.info(f"默认LLM提供者是: '{llm_manager.default_provider_name}'")

    except Exception as e:
        log.error(f"初始化LLM管理器时发生严重错误: {e}")
        sys.exit(1)

def add_line_breaks_after_punctuation(text: str, punctuations: list[str] = ['！', '？', '。', '…']) -> str:
    """
    在指定标点符号后添加换行符，以避免单行文本过长。
    :param text: 输入文本。
    :param punctuations: 需要添加换行符的标点符号列表。
    :return: 处理后的文本。
    """
    for punc in punctuations:
        # 使用正则表达式确保只在标点符号后添加一个换行符，避免重复添加
        text = re.sub(re.escape(punc) + r'(?!\n)', punc + '\n', text)
    return text

def get_video_duration(video_path: str) -> Optional[float]:
    """
    使用 ffprobe 获取视频文件的时长（秒）。
    需要系统安装 FFmpeg/ffprobe。
    """
    if not os.path.exists(video_path):
        log.warning(f"视频文件不存在，无法获取时长: {video_path}")
        return None

    command = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'json',
        video_path
    ]
    
    try:
        result = run_command(command, "ffprobe execution failed")
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        return duration
    except (RuntimeError, json.JSONDecodeError, KeyError) as e:
        log.error(f"Failed to get video duration for {video_path}: {e}")
        return None

def get_relative_url(file_path: str, request: 'Request') -> str:
    """
    根据给定的文件绝对路径和请求对象，生成一个可公开访问的静态资源URL。
    """
    # 确保项目根目录已定义，通常在主应用或路由文件中设置
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    # 计算文件相对于项目根目录的路径
    relative_path = os.path.relpath(file_path, start=project_root)
    
    # 构造URL
    base_url = str(request.base_url).rstrip('/')
    static_path = f"static/{relative_path.replace(os.path.sep, '/')}"
    
    return f"{base_url}/{static_path}"

def run_command(command: List[str], error_message: str, capture_output=True, text=True, check=True, encoding='utf-8'):
    """
    一个通用的命令执行函数，封装了 subprocess.run，提供了统一的日志记录和错误处理。
    """
    try:
        process = subprocess.run(
            command,
            capture_output=capture_output,
            text=text,
            check=check,
            encoding=encoding
        )
        log.debug(f"Command executed successfully: {' '.join(command)}")
        if process.stdout:
            log.debug(f"Stdout: {process.stdout.strip()}")
        if process.stderr:
            log.warning(f"Stderr: {process.stderr.strip()}")
        return process
    except FileNotFoundError:
        err_msg = f"Error: The command '{command[0]}' was not found. Please ensure it is installed and in your PATH."
        log.error(err_msg)
        raise RuntimeError(err_msg)
    except subprocess.CalledProcessError as e:
        log.error(f"{error_message}: {e.stderr.strip() if e.stderr else 'No stderr output.'}")
        raise

def to_slash_path(path: str) -> str:
    """
    将路径中的反斜杠'\'替换为正斜杠'/'，以确保跨平台兼容性。
    """
    return path.replace("\\", "/")
