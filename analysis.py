import os
import argparse
import logging
import json
from tqdm import tqdm
from src.utils import load_config, generate_task_id, save_scenes_to_json, check_ollama_service
from src.subtitle_parser import parse_srt_file
from src.core.scene_splitter import SceneSplitter
from src.keyword_generator import KeywordGenerator
from src.logger import log
from src.color_utils import (
    print_colored,
    print_error,
    print_warning,
    print_success,
    print_info,
)
# 屏蔽 httpx 的冗余日志，避免在调用Ollama时刷屏
logging.getLogger("httpx").setLevel(logging.WARNING)

def main(srt_file_name: str, task_id: str | None = None):
    config = load_config()
    # 在执行任何操作前，检查Ollama服务
    check_ollama_service(config)
    
    print_info("--- 阶段一: 分析字幕，生成场景草稿 ---")

    input_subtitle_path = srt_file_name

    # 检查字幕文件是否存在
    if not os.path.exists(input_subtitle_path):
        print_error(f"错误: 字幕文件未找到于 {input_subtitle_path}")
        return

    # 1. 确定任务ID并创建任务目录
    if task_id:
        print_info(f"使用指定的任务ID: {task_id}")
    else:
        task_id = generate_task_id()
        print_info(f"新任务已创建，ID: {task_id}")

    task_dir = os.path.join("storage", "tasks", task_id)
    os.makedirs(task_dir, exist_ok=True)
    cache_dir = os.path.join(task_dir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)


    # 定义缓存文件和最终文件的路径
    segments_cache_path = os.path.join(cache_dir, "segments.json")
    scenes_raw_cache_path = os.path.join(cache_dir, "scenes_raw.json")
    final_scenes_path = os.path.join(task_dir, "scenes.json")

    # 如果最终文件已存在，说明此任务已完成，为防止覆盖，直接退出
    if os.path.exists(final_scenes_path):
        print_success(f"任务 {task_id} 的最终场景文件 scenes.json 已存在。")
        print_info("阶段一已完成，无需重新运行。")
        print_info(f"==> {final_scenes_path}")
        return

    # 2. 解析SRT文件 (带缓存)
    segments = []
    if os.path.exists(segments_cache_path):
        print_info(f"发现缓存，从 {os.path.basename(segments_cache_path)} 加载片段...")
        with open(segments_cache_path, 'r', encoding='utf-8') as f:
            segments = json.load(f)
        print_success("片段加载成功。")
    else:
        with tqdm(total=1, desc="解析SRT文件") as pbar:
            segments = parse_srt_file(input_subtitle_path)
            pbar.update(1)
        
        if segments:
            print_info(f"解析完成，缓存片段到 {os.path.basename(segments_cache_path)}...")
            with open(segments_cache_path, 'w', encoding='utf-8') as f:
                json.dump(segments, f, ensure_ascii=False, indent=4)

    if not segments:
        print_error("未能从字幕文件中解析出片段，程序终止。")
        return

    # 3. 使用LLM进行语义场景分割 (带缓存)
    scenes = []
    if os.path.exists(scenes_raw_cache_path):
        print_info(f"发现缓存，从 {os.path.basename(scenes_raw_cache_path)} 加载场景...")
        with open(scenes_raw_cache_path, 'r', encoding='utf-8') as f:
            scenes = json.load(f)
        print_success(f"已加载 {len(scenes)} 个场景。")
    else:
        splitter = SceneSplitter(config, task_id)
        scenes = splitter.split(segments)

        if scenes:
            print_info(f"成功分割成 {len(scenes)} 个场景。")
            print_info(f"缓存原始场景到 {os.path.basename(scenes_raw_cache_path)}...")
            with open(scenes_raw_cache_path, 'w', encoding='utf-8') as f:
                json.dump(scenes, f, ensure_ascii=False, indent=4)

    if not scenes:
        print_error("场景分割失败，未能生成任何场景。")
        return

    # 4. 为每个场景生成关键词
    print_info("开始为场景生成关键词...")
    keyword_gen = KeywordGenerator(config)
    # 使用tqdm来包装场景列表，以显示进度条
    scenes_iterable = tqdm(scenes, desc="为场景生成关键词", unit="个")
    keyword_gen.generate_for_scenes(scenes_iterable)

    # 5. 保存最终结果供人工审核
    save_scenes_to_json(scenes, task_id)
    print_info("\n############################################################")
    print_success(f"阶段一完成！任务ID为: {task_id}")
    print_info("请打开下面路径中的 scenes.json 文件，检查并修改关键词：")
    print_info(f"==> {final_scenes_path}")
    print_info("修改完成后，请运行阶段二脚本并提供此任务ID。")
    print_info("############################################################")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="阶段一：分析字幕并生成场景关键词。")
    parser.add_argument("-s", "--srt-file", dest="srt_file", required=True, help="SRT字幕文件的路径 (可以是相对路径或绝对路径)。")
    parser.add_argument("-id", "--task-id", dest="task_id", required=False, default=None, help="可选：指定一个任务ID以恢复或继续任务。如果未提供，将创建一个新任务。")
    args = parser.parse_args()
    main(args.srt_file, args.task_id)