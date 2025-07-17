import yaml
import json
import os
import sys
from src.logger import log
from src.providers.llm import LlmManager
from typing import List, Dict

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



# def load_scenes_from_json(task_id: str) -> list:
#     """从指定任务的JSON文件中加载（可能已修改的）场景。"""
#     # This function might need refactoring if TaskManager is to be used everywhere.
#     # For now, we keep its direct dependency to avoid passing TaskManager instance around.
#     from src.core.task_manager import TaskManager
#     task_manager = TaskManager(task_id)
#     file_path = task_manager.get_path("final_scenes.json")
#     log.info(f"从文件加载场景: {file_path}")
#     try:
#         with open(file_path, 'r', encoding='utf-8') as f:
#             return json.load(f)
#     except FileNotFoundError:
#         log.error(f"错误: 场景文件 {file_path} 未找到。请先运行阶段一。")
#         return []

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
            sys.exit(1)

        log.success(f"成功加载 {len(llm_manager.providers)} 个LLM提供者: {list(llm_manager.providers.keys())}")

        if not llm_manager.default:
            log.warning("警告: 默认的LLM提供者未能加载，但有其他可用的提供者。")
            log.warning(f"程序将使用 '{llm_manager.default_provider_name}' 作为备用。")
        else:
            log.info(f"默认LLM提供者是: '{llm_manager.default_provider_name}'")

    except Exception as e:
        log.error(f"初始化LLM管理器时发生严重错误: {e}")
        sys.exit(1)
