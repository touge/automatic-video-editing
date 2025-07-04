import yaml
import json
import os
import uuid
import ollama
import sys
from src.logger import log

from src.color_utils import (
    print_colored,
    print_error,
    print_warning,
    print_success,
    print_info,
)

def load_config(config_path="config.yaml"):
    """加载YAML配置文件"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def generate_task_id() -> str:
    """生成一个唯一的任务ID"""
    return str(uuid.uuid4())

def get_task_path(task_id: str) -> str:
    """获取指定任务的目录路径"""
    return os.path.join("storage", "tasks", task_id)

def ensure_task_path(task_id: str):
    """确保任务目录存在"""
    task_path = get_task_path(task_id)
    os.makedirs(task_path, exist_ok=True)
    return task_path

def save_scenes_to_json(scenes: list, task_id: str):
    """将带有关键词的场景保存到指定任务的JSON文件，供人工审核。"""
    task_path = ensure_task_path(task_id)
    file_path = os.path.join(task_path, "scenes.json")
    print_info(f"场景和关键词已生成，保存至: {file_path}")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(scenes, f, ensure_ascii=False, indent=4)

def load_scenes_from_json(task_id: str) -> list:
    """从指定任务的JSON文件中加载（可能已修改的）场景。"""
    file_path = os.path.join(get_task_path(task_id), "scenes.json")
    print_info(f"从文件加载场景: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        log.error(f"错误: 场景文件 {file_path} 未找到。请先运行阶段一。")
        return []

def check_ollama_service(config: dict):
    """
    检查Ollama服务是否可达。如果不可达，则打印错误并中止程序。
    """
    # 检查配置中是否启用了Ollama
    ollama_config = config.get('ollama', {})
    if not ollama_config.get('model'):
        # 如果配置中没有指定Ollama模型，则认为不需要使用Ollama，跳过检查。
        return

    host = ollama_config.get('host', 'http://localhost:11434')
    timeout = 5 # 使用固定的5秒超时进行快速检查

    print_info(f"正在检查Ollama服务状态 at {host}...")
    try:
        # 使用一个专门的客户端和较短的超时时间来进行快速连接检查
        client = ollama.Client(host=host, timeout=timeout)
        # 执行一个轻量级命令来确认服务不仅在运行，而且模型API也准备好了
        client.list()
        print_success("Ollama服务连接正常。")
    except Exception:
        print_error(f"无法在{timeout}秒内连接到Ollama服务 at {host}。")
        print_error("请确认Ollama服务是否已启动，并且网络连接正常。程序将中止。")
        sys.exit(1) # 中止程序