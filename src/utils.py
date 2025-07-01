import yaml
import json
import os
import uuid

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
    print(f"场景和关键词已生成，保存至: {file_path}")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(scenes, f, ensure_ascii=False, indent=4)

def load_scenes_from_json(task_id: str) -> list:
    """从指定任务的JSON文件中加载（可能已修改的）场景。"""
    file_path = os.path.join(get_task_path(task_id), "scenes.json")
    print(f"从最终版关键词文件加载场景: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"错误: 场景文件 {file_path} 未找到。请先运行阶段一。")
        return []