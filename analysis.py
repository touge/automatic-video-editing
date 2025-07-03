import os
import argparse
import logging
from tqdm import tqdm
from src.utils import load_config, generate_task_id, save_scenes_to_json
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

def main(srt_file_name: str):
    """
    执行阶段一：从字幕文件生成带有关键词的场景JSON文件。
    """
    print_info("--- 阶段一: 分析字幕，生成场景草稿 ---")

    config = load_config()
    input_subtitle_path = srt_file_name

    # 检查字幕文件是否存在
    if not os.path.exists(input_subtitle_path):
        print_error(f"错误: 字幕文件未找到 at {input_subtitle_path}")
        return

    # 1. 生成唯一的任务ID
    task_id = generate_task_id()
    print_info(f"新任务已创建，ID: {task_id}")

    # 2. 解析SRT文件
    with tqdm(total=1, desc="解析SRT文件") as pbar:
        segments = parse_srt_file(input_subtitle_path)
        pbar.update(1)

    if not segments:
        print_error("未能从字幕文件中解析出片段，程序终止。")
        return

    # 3. 使用LLM进行语义场景分割
    splitter = SceneSplitter(config, task_id)
    scenes = splitter.split(segments)

    if not scenes:
        print_error("场景分割失败，未能生成任何场景。")
        return
    print_info(f"成功分割成 {len(scenes)} 个场景。")

    # 4. 为每个场景生成关键词
    keyword_gen = KeywordGenerator(config)
    # 使用tqdm来包装场景列表，以显示进度条
    scenes_iterable = tqdm(scenes, desc="为场景生成关键词", unit="个")
    keyword_gen.generate_for_scenes(scenes_iterable)

    # 5. 保存结果供人工审核
    save_scenes_to_json(scenes, task_id)
    print_info("\n############################################################")
    print_info(f"阶段一完成！任务ID为: {task_id}")
    print_info("请打开下面路径中的 scenes.json 文件，检查并修改关键词：")
    print_info(f"==> storage/tasks/{task_id}/scenes.json")
    print_info("修改完成后，请运行阶段二脚本并提供此任务ID。")
    print_info("############################################################")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="阶段一：分析字幕并生成场景关键词。")
    parser.add_argument("-s", "--srt-file", dest="srt_file", required=True, help="SRT字幕文件的路径 (可以是相对路径或绝对路径)。")
    args = parser.parse_args()
    main(args.srt_file)