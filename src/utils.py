import yaml
import json
import os
import sys
from src.logger import log
from src.providers.llm import LlmManager

def debug_and_exit(message):
    log.debug(f"调试输出：{message}")
    sys.exit(0)

# def save_scenes_to_json(scenes: list, task_id: str):
#     """将带有关键词的场景保存到指定任务的JSON文件，供人工审核。"""
#     task_path = ensure_task_path(task_id)
#     file_path = os.path.join(task_path, "final_scenes.json")
#     log.info(f"场景和关键词已生成，保存至: {file_path}")
#     with open(file_path, 'w', encoding='utf-8') as f:
#         json.dump(scenes, f, ensure_ascii=False, indent=4)

def load_scenes_from_json(task_id: str) -> list:
    """从指定任务的JSON文件中加载（可能已修改的）场景。"""
    # This function might need refactoring if TaskManager is to be used everywhere.
    # For now, we keep its direct dependency to avoid passing TaskManager instance around.
    from src.core.task_manager import TaskManager
    task_manager = TaskManager(task_id)
    file_path = task_manager.get_path("final_scenes.json")
    log.info(f"从文件加载场景: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        log.error(f"错误: 场景文件 {file_path} 未找到。请先运行阶段一。")
        return []

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
