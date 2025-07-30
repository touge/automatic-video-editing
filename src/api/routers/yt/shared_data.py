import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

# 简单的内存任务存储，供所有 yt 相关的路由共享
# 实际生产环境可能需要 Redis, 数据库或其他持久化存储
tasks: Dict[str, Dict[str, Any]] = {}

def get_task_folder_path(task_id: str) -> Path:
    """根据 task_id 获取任务文件夹的完整路径。"""
    from src.config_loader import config # 临时导入 config
    base_task_folder = config.get('paths.task_folder', 'tasks')
    return Path(f"{base_task_folder}/{task_id}")

def save_task_status(task_id: str):
    """将指定任务的状态保存到对应的任务目录下的 status.json 文件中。"""
    if task_id not in tasks:
        return

    task_info = tasks[task_id]
    task_dir = get_task_folder_path(task_id)
    os.makedirs(task_dir, exist_ok=True) # 确保目录存在
    
    status_file_path = task_dir / "status.json"
    
    try:
        with open(status_file_path, "w", encoding="utf-8") as f:
            json.dump(task_info, f, indent=4, ensure_ascii=False)
        # print(f"Task status for {task_id} saved to {status_file_path}") # 调试信息
    except Exception as e:
        print(f"Error saving task status for {task_id} to {status_file_path}: {e}")

def load_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """从对应的任务目录下的 status.json 文件中加载任务状态。"""
    task_dir = get_task_folder_path(task_id)
    status_file_path = task_dir / "status.json"
    
    if not status_file_path.exists():
        return None
    
    try:
        with open(status_file_path, "r", encoding="utf-8") as f:
            task_info = json.load(f)
        # print(f"Task status for {task_id} loaded from {status_file_path}") # 调试信息
        return task_info
    except Exception as e:
        print(f"Error loading task status for {task_id} from {status_file_path}: {e}")
        return None
