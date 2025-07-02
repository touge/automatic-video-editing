import os
import argparse
import math
from src.utils import load_config, load_scenes_from_json, save_scenes_to_json
from tqdm import tqdm
from src.core.asset_manager import AssetManager
from src.core.video_composer import VideoComposer
from src.logger import log

from src.color_utils import (
    print_colored,
    print_error,
    print_warning,
    print_success,
    print_info,
)

def split_scene_duration(total_duration: float, max_clip_duration: float, min_clip_duration: float) -> list[float]:
    """
    将一个较长的场景时长，根据最大和最小时长约束，智能地切分为多个片段时长。
    采用贪心算法，优先分配较长的片段，创造更自然的节奏。

    例如: 17s, max=8s, min=3s -> [8.0, 6.0, 3.0]
    """
    if total_duration <= max_clip_duration:
        # 如果总时长小于等于最大时长，则无需切分
        return [round(total_duration, 2)]

    # 1. 计算需要多少个片段
    num_clips = math.ceil(total_duration / max_clip_duration)

    # 2. 如果平均分配会导致片段过短，则减少片段数量
    if total_duration / num_clips < min_clip_duration:
        num_clips = math.floor(total_duration / min_clip_duration)
        if num_clips == 0: # 极端情况，总时长小于最小时长
            return [round(total_duration, 2)]

    if num_clips == 1:
        return [round(total_duration, 2)]

    # 3. 使用贪心算法分配时长
    durations = []
    remaining_duration = total_duration
    for i in range(num_clips):
        clips_to_go = num_clips - i

        if clips_to_go == 1:
            # 最后一个片段，分配所有剩余时长
            durations.append(remaining_duration)
            break

        # 计算当前片段能取的最大时长，同时要保证剩下的片段长度不小于min_clip_duration
        max_possible_duration = remaining_duration - (clips_to_go - 1) * min_clip_duration

        # 当前片段的时长，不能超过max_clip_duration和计算出的最大可能时长
        current_duration = min(max_clip_duration, max_possible_duration)

        durations.append(current_duration)
        remaining_duration -= current_duration

    return [round(d, 2) for d in durations]

def main(task_id: str, audio_file: str, subtitle_option: str | bool | None):
    """
    执行阶段二：根据最终的场景JSON文件和音频文件，搜索素材并合成视频。
    """
    print_info(f"\n--- 阶段二: 从任务 {task_id} 创建视频 ---")

    config = load_config()
    # 检查音频文件是否存在
    audio_path = audio_file
    if not os.path.exists(audio_path):
        log.error(f"错误: 音频文件未找到 at {audio_path}")
        return

    # 1. 加载（可能已修改的）场景
    scenes = load_scenes_from_json(task_id)
    if not scenes:
        return

    # 2. 为每个场景搜索素材
    video_config = config.get('video', {})
    max_clip_duration = video_config.get('max_clip_duration', 8.0)
    min_clip_duration = video_config.get('min_clip_duration', 3.0)

    asset_manager = AssetManager(config, task_id)
    scene_asset_paths = []
    all_assets_found = True
    scenes_updated = False # 标记是否需要回写scenes.json

    scenes_iterable = tqdm(scenes, desc="为场景准备素材", unit="个")
    for i, scene in enumerate(scenes_iterable):
        # 智能切分场景时长
        duration_parts = split_scene_duration(scene['duration'], max_clip_duration, min_clip_duration)
        scene['duration_parts'] = duration_parts # 将切分结果存回scene
        num_assets_needed = len(duration_parts)

        # 检查是否已有缓存的、可用的素材路径
        cached_asset_paths = scene.get('asset_paths', [])
        if cached_asset_paths and len(cached_asset_paths) == num_assets_needed and all(os.path.exists(p) for p in cached_asset_paths):
            # log.info(f"场景 {i+1} 使用已缓存的素材，跳过搜索。")
            scene_asset_paths.append(cached_asset_paths)
            continue

        # 如果没有缓存或缓存无效，则查找素材
        asset_paths = asset_manager.find_assets_for_scene(scene, num_assets_needed)
        
        if not asset_paths or len(asset_paths) < num_assets_needed:
            log.error(f"\n\n错误: 经过多轮尝试后，仍未能为场景 {i+1} 找到足够的素材。")
            log.error(f"场景文本: \"{scene['text']}\"")
            log.error("程序将终止，以避免生成不完整的视频。")
            log.error("建议：请检查 scenes.json 中该场景的关键词，或增加 config.yaml 中 asset_search.max_keyword_retries 的次数。")
            all_assets_found = False
            break
        
        # 成功找到素材，将其路径存回场景字典
        scene['asset_paths'] = asset_paths
        scenes_updated = True
        scene_asset_paths.append(asset_paths)

    # 在继续之前，如果素材路径有更新，则保存回scenes.json
    if scenes_updated:
        print_info("素材路径已更新，正在保存回 scenes.json...")
        save_scenes_to_json(scenes, task_id)

    # 如果任何一个场景的素材查找失败，则终止程序
    if not all_assets_found:
        return

    # 3. 处理字幕选项
    subtitle_path = None
    if subtitle_option is None:
        # --with-subtitles 参数未提供，不添加字幕
        print_info("未提供 --with-subtitles 参数，将不添加字幕。")
        subtitle_path = None
    elif subtitle_option is True: # 使用 --with-subtitles 但未指定文件
        print_info("将根据场景数据自动生成字幕。")
        subtitle_path = "GENERATE" # 特殊标记，让composer生成
    elif isinstance(subtitle_option, str): # 指定了SRT文件
        print_info(f"将使用指定的字幕文件: {subtitle_option}")
        subtitle_path = subtitle_option
        if not os.path.exists(subtitle_path):
            log.warning(f"指定的字幕文件未找到: {subtitle_path}。将不添加字幕。")
            subtitle_path = None

    # 4. 合成最终视频
    if any(scene_asset_paths):
        composer = VideoComposer(config, task_id)
        composer.assemble_video(scenes, scene_asset_paths, audio_path, subtitle_path)
    else:
        log.error("没有足够的素材来生成视频。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="阶段二：从场景文件合成视频。")
    parser.add_argument("--with-task-id", dest="task_id", required=True, help="要处理的任务ID。")
    parser.add_argument("--with-audio", dest="audio_file", required=True, help="音频文件的路径 (例如 my_vlog.mp3)。")
    parser.add_argument("--with-subtitles", dest="subtitle_option", nargs='?', const=True, default=None,
                        help="将字幕烧录到视频中。若只提供此参数，则自动生成字幕；若提供文件路径，则使用该文件。")
    args = parser.parse_args()
    main(args.task_id, args.audio_file, args.subtitle_option)
