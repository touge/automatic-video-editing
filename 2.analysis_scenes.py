import os
import argparse
import json
from tqdm import tqdm
import bootstrap
from src.config_loader import config
from src.utils import save_scenes_to_json, check_llm_providers
from src.keyword_generator import KeywordGenerator
from src.logger import log
from src.color_utils import (
    print_error,
    print_info,
    print_success,
)

def main(task_id: str):
    """
    为场景生成关键词。
    """
    print_info(f"\n--- 步骤二: 从任务 {task_id} 为场景生成关键词 ---")
    check_llm_providers(config.data)

    task_dir = os.path.join("storage", "tasks", task_id)
    cache_dir = os.path.join(task_dir, ".cache")
    
    # 定义缓存文件和最终文件的路径
    scenes_raw_cache_path = os.path.join(cache_dir, "scenes_raw.json")
    if not os.path.exists(scenes_raw_cache_path):
        print_error(f"错误: 未找到任务 {task_id} 的原始场景文件。")
        print_error(f"请先运行 `analysis_subtitles.py` 来生成 {os.path.basename(scenes_raw_cache_path)}。")
        return
    final_scenes_path = os.path.join(task_dir, "scenes.json")

    # 如果最终文件已存在，说明此步骤已完成
    if os.path.exists(final_scenes_path):
        print_success(f"任务 {task_id} 的最终场景文件 scenes.json 已存在。")
        print_info("关键词生成步骤已完成，无需重新运行。")
        return

    # 加载原始场景
    print_info(f"从 {os.path.basename(scenes_raw_cache_path)} 加载原始场景...")
    with open(scenes_raw_cache_path, 'r', encoding='utf-8') as f:
        scenes = json.load(f)
    print_success(f"已加载 {len(scenes)} 个原始场景。")

    if not scenes:
        print_error("场景分割失败，未能生成任何场景。")
        return

    # 1. 为每个场景生成关键词
    print_info("开始为场景生成关键词...")
    keyword_gen = KeywordGenerator(config)
    scenes_iterable = tqdm(scenes, desc="为场景生成关键词", unit="个")
    keyword_gen.generate_for_scenes(scenes_iterable)

    # 2. 保存最终结果供人工审核
    save_scenes_to_json(scenes, task_id)
    print_info("\n############################################################")
    print_success(f"关键词生成完成！任务ID为: {task_id}")
    print_info("请打开下面路径中的 scenes.json 文件，检查并修改关键词：")
    print_info(f"==> {final_scenes_path}")
    print_info("修改完成后，请运行 composition.py 脚本并提供此任务ID来合成视频。")
    print_info("############################################################")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="步骤二：为场景生成关键词。")
    parser.add_argument("-id", "--task-id", dest="task_id", required=True, help="要处理的任务ID。")
    args = parser.parse_args()
    main(args.task_id)
