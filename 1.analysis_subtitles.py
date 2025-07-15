import os
import argparse
import logging
import json
from tqdm import tqdm
import bootstrap
from src.config_loader import config
from src.utils import check_llm_providers, generate_task_id, debug_and_exit
from src.subtitle_parser import parse_srt_file
from src.core.scene_splitter import SceneSplitter
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


def process_merged_scenes(scenes: list) -> list:
    pass

def post_process_scenes(scenes: list, min_duration: float = 3.0, max_duration: float = 20.0) -> list:
    """
    对AI分割的场景进行后处理，确保场景时长在合理范围内。
    - 合并过短的场景
    - 拆分过长的场景
    """
    if not scenes:
        return []

    # 第一步：合并过短的场景
    merged_scenes = []
    temp_scene = None

    for scene in scenes:
        if temp_scene is None:
            temp_scene = scene.copy()
        else:
            # 如果当前临时场景太短，则与下一个场景合并
            if temp_scene['duration'] < min_duration:
                temp_scene['text'] += " " + scene['text']
                temp_scene['duration'] += scene['duration']
                temp_scene['scene_end'] = scene['scene_end']
                # 合并源字幕行
                if 'segments' in temp_scene and 'segments' in scene:
                    temp_scene['segments'].extend(scene['segments'])
            else:
                merged_scenes.append(temp_scene)
                temp_scene = scene.copy()
    
    if temp_scene:
        merged_scenes.append(temp_scene)

    # 第二步：拆分过长的场景
    final_scenes = []
    for scene in merged_scenes:
        if scene['duration'] <= max_duration:
            final_scenes.append(scene)
            continue

        # 如果场景过长，需要拆分
        print_warning(f"发现超长场景 (时长: {scene['duration']:.2f}s)，将尝试用代码逻辑进行拆分...")
        
        # 一个非常基础的拆分逻辑：按比例大致拆分
        # 更优的逻辑可以基于句子边界（句号、问号等）
        num_splits = int(scene['duration'] // max_duration) + 1
        avg_duration = scene['duration'] / num_splits
        
        # 假设 segments 在 scene 中是可用的
        if 'segments' not in scene or not scene['segments']:
            # 如果没有segments信息，无法准确拆分，只能跳过
            print_error("无法拆分超长场景，因为缺少详细的片段信息。")
            final_scenes.append(scene)
            continue

        current_time = scene['scene_start']
        current_segments = []
        for i in range(num_splits):
            split_end_time = current_time + avg_duration
            
            # 找到最接近平均时长的片段边界
            split_point_segment_index = -1
            for j, seg in enumerate(scene['segments']):
                if seg['end'] >= split_end_time:
                    split_point_segment_index = j
                    break
            
            # 如果找不到合适的分割点（比如到了最后），就全部分配
            if split_point_segment_index == -1:
                split_segments = scene['segments']
            else:
                split_segments = scene['segments'][:split_point_segment_index + 1]
                scene['segments'] = scene['segments'][split_point_segment_index + 1:]

            if not split_segments:
                continue

            new_scene_text = " ".join([s['text'] for s in split_segments])
            new_scene_start = split_segments[0]['start']
            new_scene_end = split_segments[-1]['end']
            new_scene_duration = new_scene_end - new_scene_start

            final_scenes.append({
                "text": new_scene_text,
                "scene_start": new_scene_start,
                "scene_end": new_scene_end,
                "duration": new_scene_duration,
                "segments": split_segments
            })
            
            if not scene['segments']:
                break # 所有片段都已分配完毕

    return final_scenes

# process
# 2. 解析SRT文件 (带缓存)
def process_parse_srt_file(input_subtitle_path, segments_cache_path) -> list:
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
            print_success(f"解析完成，缓存片段到 {os.path.basename(segments_cache_path)}...")
            with open(segments_cache_path, 'w', encoding='utf-8') as f:
                json.dump(segments, f, ensure_ascii=False, indent=4)

    if not segments:
        print_error("未能从字幕文件中解析出片段，程序终止。")
        return
    return segments

def main(srt_file_name: str, task_id: str | None = None):
    # check_llm_providers(config.data)

    # 在执行任何操作前，检查Ollama服务
    check_llm_providers(config)
    
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
        print_success(f"新任务已创建，ID: {task_id}")

    task_dir = os.path.join("storage", "tasks", task_id)
    os.makedirs(task_dir, exist_ok=True)
    cache_dir = os.path.join(task_dir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)

    # 定义缓存文件路径
    segments_cache_path = os.path.join(cache_dir, "segments.json")
    scenes_raw_cache_path = os.path.join(cache_dir, "scenes_raw.json")

    # 2. 解析SRT文件 (带缓存)
    segments= process_parse_srt_file(input_subtitle_path, segments_cache_path)
    

    debug_and_exit(f"segments: {segments}")

    # 3. 使用LLM进行语义场景分割 (带缓存)
    scenes = []
    if os.path.exists(scenes_raw_cache_path):
        print_info(f"发现缓存，从 {os.path.basename(scenes_raw_cache_path)} 加载原始场景...")
        with open(scenes_raw_cache_path, 'r', encoding='utf-8') as f:
            scenes = json.load(f)
        print_success(f"已加载 {len(scenes)} 个原始场景。")
    else:
        splitter = SceneSplitter(config, task_id)
        # AI进行初步分割
        initial_scenes = splitter.split(segments)

        if initial_scenes:
            print_success(f"AI初步分割成 {len(initial_scenes)} 个场景。")
            
            # 代码进行后处理
            print_info("正在进行代码后处理，优化场景分割...")
            min_scene_duration = config.get("video.min_clip_duration", 3.0)
            max_scene_duration = config.get("video.max_clip_duration", 8.0) * 2.5 # 放宽最大场景限制
            scenes = post_process_scenes(initial_scenes, min_duration=min_scene_duration, max_duration=max_scene_duration)
            print_success(f"后处理完成，最终生成 {len(scenes)} 个优化场景。")

            print_info(f"缓存优化后的场景到 {os.path.basename(scenes_raw_cache_path)}...")
            with open(scenes_raw_cache_path, 'w', encoding='utf-8') as f:
                json.dump(scenes, f, ensure_ascii=False, indent=4)
        else:
            scenes = []

    if not scenes:
        print_error("场景分割失败，未能生成任何场景。")
        return

    print_info("\n############################################################")
    print_success(f"字幕解析和场景分割完成！任务ID为: {task_id}")
    print_info(f"原始场景数据已保存到: {scenes_raw_cache_path}")
    print_info("接下来，请运行关键词生成脚本:")
    print_colored(f"python analysis_scenes.py --task-id {task_id}", "cyan")
    print_info("############################################################")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="步骤一：分析字幕并分割场景。")
    parser.add_argument("-s", "--srt-file", dest="srt_file", required=True, help="SRT字幕文件的路径 (可以是相对路径或绝对路径)。")
    parser.add_argument("-id", "--task-id", dest="task_id", required=False, default=None, help="可选：指定一个任务ID以恢复或继续任务。如果未提供，将创建一个新任务。")
    args = parser.parse_args()
    main(args.srt_file, args.task_id)
