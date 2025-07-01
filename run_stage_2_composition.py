import os
import argparse
import math
from src.utils import load_config, load_scenes_from_json
from src.core.asset_manager import AssetManager
from src.core.video_composer import VideoComposer

def split_scene_duration(total_duration: float, max_clip_duration: float, min_clip_duration: float) -> list[float]:
    """
    将一个较长的场景时长，根据最大和最小时长约束，智能地切分为多个片段时长。
    
    例如: 17s, max=8s, min=3s -> [8.0, 4.5, 4.5]
    """
    if total_duration <= max_clip_duration:
        return [total_duration]

    num_clips = math.ceil(total_duration / max_clip_duration)
    
    # 初始平均分配
    avg_duration = total_duration / num_clips
    
    # 如果平均时长小于最小限制，需要减少片段数量
    if avg_duration < min_clip_duration:
        num_clips = math.floor(total_duration / min_clip_duration)
        if num_clips == 0: # 极端情况，总时长小于最小时长
            return [total_duration]

    # 重新计算分配
    base_duration = total_duration / num_clips
    durations = [base_duration] * num_clips
    
    # 在实践中，可以加入一些随机性或更复杂的分配逻辑，这里为了简单直接平均分配
    # 这里返回的是一个近似值列表，可以在具体使用时再做微调
    return [round(d, 2) for d in durations]

def main(task_id: str, audio_file: str, subtitle_option: str | bool | None):
    """
    执行阶段二：根据最终的场景JSON文件和音频文件，搜索素材并合成视频。
    """
    print(f"\n--- 阶段二: 从任务 {task_id} 创建视频 ---")

    config = load_config()
    # 检查音频文件是否存在
    audio_path = audio_file
    if not os.path.exists(audio_path):
        print(f"错误: 音频文件未找到 at {audio_path}")
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

    for scene in scenes:
        scene_duration = scene['duration']
        # 智能切分场景时长
        duration_parts = split_scene_duration(scene_duration, max_clip_duration, min_clip_duration)
        scene['duration_parts'] = duration_parts # 将切分结果存回scene
        
        num_assets_needed = len(duration_parts)
        print(f"场景 \"{scene['text'][:20]}...\" (时长 {scene_duration}s) 需要 {num_assets_needed} 个素材。")

        # 为一个场景查找多个素材
        asset_paths = asset_manager.find_assets_for_scene(scene, num_assets_needed)
        
        if asset_paths and len(asset_paths) == num_assets_needed:
            scene_asset_paths.append(asset_paths)
        else:
            print(f"警告: 未能为场景 \"{scene['text'][:30]}...\" 找到足够数量({num_assets_needed})的素材。")
            # 补位逻辑：可以用一个占位符或空列表，合成时跳过此场景
            scene_asset_paths.append([])

    # 3. 处理字幕选项
    subtitle_path = None
    if subtitle_option is None:
        # --with-subtitles 参数未提供，不添加字幕
        print("未提供 --with-subtitles 参数，将不添加字幕。")
        subtitle_path = None
    elif subtitle_option is True: # 使用 --with-subtitles 但未指定文件
        print("将根据场景数据自动生成字幕。")
        subtitle_path = "GENERATE" # 特殊标记，让composer生成
    elif isinstance(subtitle_option, str): # 指定了SRT文件
        print(f"将使用指定的字幕文件: {subtitle_option}")
        subtitle_path = subtitle_option
        if not os.path.exists(subtitle_path):
            print(f"警告: 指定的字幕文件未找到: {subtitle_path}。将不添加字幕。")
            subtitle_path = None

    # 4. 合成最终视频
    if any(scene_asset_paths):
        composer = VideoComposer(config, task_id)
        composer.assemble_video(scenes, scene_asset_paths, audio_path, subtitle_path)
    else:
        print("错误: 没有足够的素材来生成视频。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="阶段二：从场景文件合成视频。")
    parser.add_argument("--with-task-id", dest="task_id", required=True, help="要处理的任务ID。")
    parser.add_argument("--with-audio", dest="audio_file", required=True, help="音频文件的路径 (例如 my_vlog.mp3)。")
    parser.add_argument("--with-subtitles", dest="subtitle_option", nargs='?', const=True, default=None,
                        help="将字幕烧录到视频中。若只提供此参数，则自动生成字幕；若提供文件路径，则使用该文件。")
    args = parser.parse_args()
    main(args.task_id, args.audio_file, args.subtitle_option)