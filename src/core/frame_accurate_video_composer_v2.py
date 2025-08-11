# ==================================================================================================
# 帧精确视频合成器 V2
#
# 功能描述:
# 本脚本定义了 `FrameAccurateVideoComposerV2` 类，是一个用于根据结构化的 JSON 输入
# 以编程方式创建视频的强大工具。它擅长将视频片段以帧级别的精度拼接在一起，以匹配预定义的时长。
#
# 主要特性:
# - JSON驱动结构: 通过JSON文件定义视频构成，指明段落、场景和素材路径。
# - 帧精确计时: 根据目标时长精确计算并为每个场景分配帧数，确保段落的时长精确无误。
# - 动态素材时长: 使用 `ffprobe` 获取视频素材的真实时长，用于精确计算。
# - GPU加速: 自动检测并利用NVIDIA (NVENC) 硬件加速进行FFmpeg编码，并可回退到CPU。
# - 错误处理与恢复: 包含严格模式，可在失败时中止流程，并提供先进的诊断与恢复机制，
#   用以识别和替换导致FFmpeg失败的损坏视频素材。
# - 音频同步: 将最终的视频与主音轨合并。如果视频比音频短，它会用黑屏填充视频以匹配音频的长度。
# - 并发处理: 使用 `ThreadPoolExecutor` 加快获取视频时长的过程。
# - 模块化与可配置: 设计为大型系统的一部分，可配置分辨率、帧率、临时目录等参数。
# ==================================================================================================

import json
import subprocess
from tqdm import tqdm
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from time import sleep
import os
import shutil
from src.core.asset_manager import AssetManager
from src.config_loader import config
from src.logger import log
from src.utils import run_command
# from ..utils import get_terminal_width_by_ratio
from os.path import basename


class FrameAccurateVideoComposerV2:
    def __init__(
        self,
        task_id,
        video_struct_path,
        input_audio_path,
        output_video_path,
        temp_dir="temp_segments",
        resolution=(1920, 1080),
        fps=30,
        trim_audio=True,
        silent=True,
        strict_mode=True,
        max_workers=8
    ):
        """
        ✅ 初始化配置参数
        :param task_id: 当前任务的ID
        :param video_struct_path: 视频结构 JSON 文件路径（含片段和素材列表）
        :param input_audio_path: 合并用音频文件路径
        :param output_video_path: 最终输出视频路径
        :param temp_dir: 存储中间段落视频的目录
        :param resolution: 输出视频分辨率，默认 1920x1080
        :param fps: 输出视频帧率，默认 30
        :param trim_audio: 是否根据总视频时长裁剪音频
        :param silent: 是否静默运行 FFmpeg（不打印过程）
        :param strict_mode: 若任一段落失败则终止流程
        :param max_workers: 获取素材时长时使用的最大线程数
        """
        self.task_id = task_id
        self.video_struct_path = Path(video_struct_path)
        self.input_audio_path = Path(input_audio_path)
        self.output_video_path = Path(output_video_path)
        self.temp_dir = Path(temp_dir)
        self.width, self.height = resolution
        self.fps = fps
        self.trim_audio = trim_audio
        self.silent = silent
        self.strict_mode = strict_mode
        self.max_workers = max_workers
        self.structure = []
        self.gpu_enabled = self.check_gpu_support()

    def load_structure(self):
        """📦 加载 JSON 视频结构信息"""
        with open(self.video_struct_path, "r", encoding="utf-8") as f:
            self.structure = json.load(f)

    def check_gpu_support(self):
        """🔍 动态检查 FFmpeg 是否支持 NVIDIA NVENC 硬件加速"""
        try:
            result = run_command(["ffmpeg", "-encoders"], "Failed to check ffmpeg encoders.")
            if "h264_nvenc" in result.stdout:
                log.info("✅ NVIDIA GPU acceleration (h264_nvenc) detected. Hardware acceleration will be enabled.")
                return True
            else:
                log.info("ℹ️ NVIDIA GPU acceleration not detected. Encoding will use CPU.")
                return False
        except RuntimeError as e:
            log.warning(f"⚠️ Could not check for GPU support, proceeding with CPU. Reason: {e}")
            return False

    def get_duration(self, path):
        """⏱️ 获取素材的真实时长（使用 ffprobe），返回高精度浮点数"""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ]
        try:
            result = run_command(cmd, f"Failed to get duration for {path}")
            return float(result.stdout.strip())
        except (RuntimeError, ValueError):
            return 0.0

    def process_segment(self, segment, seg_index):
        """🎬 基于帧数分配段落时长，生成段落视频，确保零误差"""
        scenes = segment.get("scenes", [])

        # 检查场景列表是否为空
        if not scenes:
            raise ValueError(f"Data integrity error: Segment {seg_index:02d} contains no scenes. Processing cannot continue.")

        target_duration = segment["duration"]
        asset_paths = [scene["asset_path"] for scene in scenes]

        # 验证每个场景都包含有效的 'time' 字段
        for i, scene in enumerate(scenes):
            if "time" not in scene or not isinstance(scene["time"], (int, float)) or scene["time"] <= 0:
                raise ValueError(f"❌ Scene {i} is missing a valid 'time' field → {scene.get('asset_path')}")

        # 计算目标时长所需的总帧数
        target_total_frames = int(round(target_duration * self.fps))
        
        # 并发获取每个素材文件的实际时长
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            real_durations = list(tqdm(executor.map(self.get_duration, asset_paths),
                                    total=len(scenes),
                                    desc=f"⏱️ Getting asset durations for Segment {seg_index:02d}"))
        for scene, real_dur in zip(scenes, real_durations):
            scene["real_duration"] = real_dur

        # 根据每个场景的 'time' 比例，在场景间分配总帧数
        total_time_ratio = sum(scene["time"] for scene in scenes)
        allocated_frames_sum = 0
        for i, scene in enumerate(scenes):
            if i == len(scenes) - 1:
                # 将剩余的帧分配给最后一个场景，以避免舍入误差
                scene["allocated_frames"] = target_total_frames - allocated_frames_sum
            else:
                ratio = scene["time"] / total_time_ratio
                frames = int(round(ratio * target_total_frames))
                scene["allocated_frames"] = frames
                allocated_frames_sum += frames
        
        # 计算每个场景分配到的时长
        for scene in scenes:
            scene["allocated_duration"] = scene["allocated_frames"] / self.fps

        input_args, filter_lines, concat_labels = [], [], []
        for idx, scene in enumerate(scenes):
            input_args += ["-i", scene["asset_path"]]
            
            frames = scene["allocated_frames"]
            v_label = f"v{idx}"
            
            base_filter = (f"[{idx}:v]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                           f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={self.fps}")

            pad_filter = ""
            allocated_duration = frames / self.fps
            real_duration = scene.get("real_duration", 0)
            if allocated_duration > real_duration and real_duration > 0:
                pad_duration = allocated_duration - real_duration
                pad_filter = f",tpad=stop_mode=clone:stop_duration={pad_duration}"

            trim_and_pts_filter = f",select='between(n,0,{frames-1})',setpts=PTS-STARTPTS[{v_label}];"
            
            filter_lines.append(base_filter + pad_filter + trim_and_pts_filter)
            concat_labels.append(f"[{v_label}]")

            origin = scene["time"]
            allocated = scene["allocated_duration"]
            compensated = round(allocated - origin, 3)
            print(f"🎞️ {basename(scene['asset_path'])} → Original:{origin}s, Compensated:{compensated}s, Calculated:{allocated:.3f}s ({frames} frames)")

        filter_complex = "".join(filter_lines)
        filter_complex += f"{''.join(concat_labels)}concat=n={len(scenes)}:v=1:a=0[outv]"

        output_path = self.temp_dir / f"segment_{seg_index:02d}.mp4"

        if output_path.exists() and output_path.stat().st_size > 1024:
            print(f"✅ Segment {seg_index:02d} already exists, skipping generation.")
            return (output_path, target_total_frames)
        
        encoder_opts = []
        if self.gpu_enabled:
            encoder_opts = ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "23"]
        else:
            encoder_opts = ["-c:v", "libx264", "-crf", "23", "-preset", "ultrafast"]

        ffmpeg_cmd = ["ffmpeg"] + input_args + [
            "-filter_complex", filter_complex,
            "-map", "[outv]",
        ] + encoder_opts + [
            "-pix_fmt", "yuv420p",
            "-threads", "4", 
            "-y", str(output_path)
        ]

        run_command(
            ffmpeg_cmd,
            f"Failed to process segment {seg_index}",
            capture_output=self.silent, # 仅在静默模式下捕获输出
        )

        if not output_path.exists() or output_path.stat().st_size < 1024:
            print(f"\n🧨 Segment {seg_index:02d} generation failed → {output_path}")
            for path in asset_paths:
                print(f"  📄 Source asset: {path}")
            if self.strict_mode:
                raise RuntimeError(f"❌ Strict mode engaged: Segment {seg_index:02d} video generation failed")
            return None
        
        real_output_duration = self.get_duration(output_path)
        real_output_frames = int(round(real_output_duration * self.fps))
        frame_diff = real_output_frames - target_total_frames
        
        planned_duration_str = f"{target_total_frames / self.fps:.3f}s"
        real_duration_str = f"{real_output_duration:.3f}s"
        
        print(f"📊 Segment {seg_index:02d}: Planned {target_total_frames} frames ({planned_duration_str}), Generated {real_output_frames} frames ({real_duration_str}), Frame difference: {frame_diff:+} frames\n")

        return (output_path, target_total_frames)

    def _test_scene_combination(self, scenes_to_test: list, output_filename: str) -> bool:
        """测试一组场景是否可以成功合并"""
        if not scenes_to_test:
            return True
        
        input_args, filter_lines, concat_labels = [], [], []
        total_frames = 0

        for idx, scene in enumerate(scenes_to_test):
            input_args += ["-i", scene["asset_path"]]
            frames = scene["allocated_frames"]
            total_frames += frames
            v_label = f"v{idx}"
            
            base_filter = (f"[{idx}:v]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                           f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={self.fps}")
            
            pad_filter = ""
            allocated_duration = frames / self.fps
            real_duration = scene.get("real_duration", 0)
            if allocated_duration > real_duration and real_duration > 0:
                pad_duration = allocated_duration - real_duration
                pad_filter = f",tpad=stop_mode=clone:stop_duration={pad_duration}"

            trim_and_pts_filter = f",select='between(n,0,{frames-1})',setpts=PTS-STARTPTS[{v_label}];"
            
            filter_lines.append(base_filter + pad_filter + trim_and_pts_filter)
            concat_labels.append(f"[{v_label}]")

        filter_complex = "".join(filter_lines)
        filter_complex += f"{''.join(concat_labels)}concat=n={len(scenes_to_test)}:v=1:a=0[outv]"

        output_path = self.temp_dir / output_filename
        
        encoder_opts = ["-c:v", "libx264", "-crf", "23", "-preset", "ultrafast"]
        if self.gpu_enabled:
            encoder_opts = ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "23"]

        ffmpeg_cmd = ["ffmpeg"] + input_args + [
            "-filter_complex", filter_complex,
            "-map", "[outv]",
        ] + encoder_opts + [
            "-pix_fmt", "yuv420p",
            "-threads", "4", 
            "-y", str(output_path)
        ]

        try:
            result = run_command(
                ffmpeg_cmd,
                f"Diagnostic test failed for {output_filename}",
                capture_output=True # 为诊断始终捕获输出
            )
        except RuntimeError as e:
            log.debug(f"Test combination failed. FFmpeg command failed: {e}")
            if output_path.exists():
                os.remove(output_path)
            return False
        
        if not output_path.exists() or output_path.stat().st_size < 1024:
            log.debug(f"Test combination failed. FFmpeg stderr:\n{result.stderr}")
            if output_path.exists():
                os.remove(output_path)
            return False
        
        if output_path.exists():
            os.remove(output_path)
        return True

    def _replace_asset_for_scene(self, scene: dict) -> bool:
        """为有问题的场景替换素材"""
        log.info(f"  -> Replacing asset for scene: {scene.get('asset_path')}")
        try:
            asset_manager = AssetManager(config, self.task_id)
            online_search_count = config.get('asset_search', {}).get('online_search_count', 10)
        except Exception as e:
            log.error(f"  -> Replacement failed: Could not initialize AssetManager. Error: {e}")
            return False

        old_asset_path = scene.get('asset_path')
        found_video_info_list = asset_manager.find_assets_for_scene(scene, online_search_count)
        
        if not found_video_info_list:
            log.error(f"  -> Could not find a replacement asset.")
            return False

        new_asset_path = found_video_info_list[0].get('local_path')
        if not new_asset_path or not os.path.exists(new_asset_path):
            log.error(f"  -> AssetManager returned an invalid new asset path.")
            return False

        try:
            if os.path.exists(old_asset_path):
                os.remove(old_asset_path)
            shutil.move(new_asset_path, old_asset_path)
            log.success(f"  -> Successfully replaced asset, moving '{new_asset_path}' to '{old_asset_path}'")
            return True
        except Exception as e:
            log.error(f"  -> File replacement operation failed: {e}")
            return False

    def _handle_segment_failure(self, segment: dict, seg_index: int) -> bool:
        """处理失败的段落，进行诊断和恢复"""
        log.warning(f"Entering diagnostic and recovery mode for failed Segment {seg_index}...")
        scenes = segment.get("scenes", [])
        if len(scenes) <= 1:
            log.warning("Segment contains only one or zero scenes, attempting direct replacement.")
            if scenes and self._replace_asset_for_scene(scenes[0]):
                return True
            return False

        while True:
            good_scenes = []
            found_faulty = False
            for i, scene in enumerate(scenes):
                log.info(f"  -> Diagnostic test: Combining scene {i+1}/{len(scenes)}...")
                test_combination = good_scenes + [scene]
                
                if not self._test_scene_combination(test_combination, f"diag_test_{seg_index}.mp4"):
                    log.error(f"  -> Faulty asset identified: Scene {i} ({scene.get('asset_path')})")
                    found_faulty = True
                    
                    if not self._replace_asset_for_scene(scene):
                        log.error("  -> Asset replacement failed, aborting recovery for this segment.")
                        return False
                    
                    # 素材替换成功后，需要重新获取它的真实时长
                    new_duration = self.get_duration(scene['asset_path'])
                    scene['real_duration'] = new_duration

                    log.info("  -> Asset replaced successfully. Re-validating the entire segment from the beginning.")
                    break
                else:
                    good_scenes.append(scene)
            
            if not found_faulty:
                log.success(f"Diagnosis complete: All assets in Segment {seg_index} are compatible. Recovery successful.")
                return True

    def combine_segments(self, segment_results, audio_duration):
        """📽️ V2: 使用 concat 滤镜合并所有段落，并用 tpad 滤镜确保视频与音频同长"""
        valid_segment_results = [r for r in segment_results if r and r[0] and r[0].exists() and r[0].stat().st_size > 1024]
        if not valid_segment_results:
            raise RuntimeError("❌ No valid segments available to combine.")

        input_args = []
        concat_labels = []
        for i, result in enumerate(valid_segment_results):
            input_args.extend(["-i", str(result[0])])
            concat_labels.append(f"[{i}:v]")

        # 计算视频总时长和需要填充的黑场时长
        total_video_duration = sum(self.get_duration(r[0]) for r in valid_segment_results)
        padding_duration = audio_duration - total_video_duration
        
        filter_complex_parts = [
            f"{''.join(concat_labels)}concat=n={len(valid_segment_results)}:v=1:a=0[v_concat];"
        ]

        # 只有在视频比音频短的情况下才添加 tpad 滤镜
        if padding_duration > 0:
            log.warning(f"📹 Video duration ({total_video_duration:.3f}s) is shorter than audio ({audio_duration:.3f}s). Padding with {padding_duration:.3f}s of black screen.")
            # 使用 tpad 滤镜在视频末尾添加黑色帧来补足时长
            filter_complex_parts.append(f"[v_concat]tpad=stop_duration={padding_duration}:color=black[v_padded];")
            video_map_label = "[v_padded]"
        else:
            video_map_label = "[v_concat]"

        filter_complex = "".join(filter_complex_parts)
        
        # 将音频作为独立输入
        audio_input = ["-i", str(self.input_audio_path)]
        
        # 构建最终命令
        ffmpeg_cmd = ["ffmpeg"] + input_args + audio_input + [
            "-filter_complex", filter_complex,
            "-map", video_map_label,
            "-map", f"{len(valid_segment_results)}:a", # 音频是最后一个输入
            "-c:v", "libx264", # 视频流需要重新编码以应用滤镜
            "-crf", "23",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(audio_duration), # V2.1 修正: 使用 -t 精确控制最终时长
            "-y", str(self.output_video_path)
        ]
        
        if self.gpu_enabled:
            ffmpeg_cmd[ffmpeg_cmd.index("-c:v") + 1] = "h264_nvenc"
            ffmpeg_cmd[ffmpeg_cmd.index("-preset") + 1] = "p7"
            # 移除旧的CRF，为NVENC插入CQ
            ffmpeg_cmd.pop(ffmpeg_cmd.index("-crf") + 1)
            ffmpeg_cmd[ffmpeg_cmd.index("-crf")] = "-cq"
            ffmpeg_cmd.insert(ffmpeg_cmd.index("-cq") + 1, "23")


        print("\n🔗 Combining all segments using V2 filter chain...")
        try:
            run_command(
                ffmpeg_cmd,
                "Failed to combine segments",
                capture_output=self.silent,
            )
        except RuntimeError:
            log.error("FFmpeg combine process failed.")
        
        if self.output_video_path.exists() and self.output_video_path.stat().st_size > 0:
            final_video_duration = self.get_duration(self.output_video_path)
            duration_diff = final_video_duration - audio_duration
            
            print(f"\n✅ Final Validation (V2):\n"
                  f"  - Target audio duration: {audio_duration:.3f}s\n"
                  f"  - Final video duration: {final_video_duration:.3f}s\n"
                  f"  - Duration difference: {duration_diff:+.3f}s")


    def execute(self):
        """🏁 V2 执行流程: 移除错误的视频时长对齐逻辑"""
        self.load_structure()
        self.temp_dir.mkdir(exist_ok=True)

        true_audio_duration = self.get_duration(self.input_audio_path)
        log.info(f"🔊 Target audio duration: {true_audio_duration:.3f}s")

        # V2 修正: 移除在 execute 方法中修改视频结构的行为。
        # 时长对齐应在最终合并时处理，而不是通过修改片段时长。
        total_planned_video_duration = sum(seg["duration"] for seg in self.structure)
        log.info(f"🎞️ Planned total video duration: {total_planned_video_duration:.3f}s")

        segment_results = []
        max_retries = 1 # 每个段落的最大恢复尝试次数
        print(f"\n🎞️ Found {len(self.structure)} video segments to process")
        for i, segment in enumerate(self.structure):
            print(f"\n🎬 Processing Segment {i+1}/{len(self.structure)}")
            
            result = None
            for attempt in range(max_retries + 1):
                try:
                    result = self.process_segment(segment, i)
                    break # 如果成功，则跳出重试循环
                except Exception as e:
                    log.error(f"Failed to generate Segment {i} (Attempt {attempt + 1}/{max_retries + 1}). Error: {e}")
                    if attempt < max_retries and self.strict_mode is False:
                        recovery_successful = self._handle_segment_failure(segment, i)
                        if recovery_successful:
                            log.success(f"Recovery successful. Retrying Segment {i}...")
                            continue # 继续下一次尝试
                        else:
                            log.error(f"Recovery failed. Aborting processing for Segment {i}.")
                            result = None # 标记为失败
                            break # 恢复失败，跳出重试
                    else:
                        log.error(f"Max retries reached or strict mode is on. Segment {i} has failed permanently.")
                        if self.strict_mode:
                            raise e # 严格模式下直接抛出异常
                        result = None # 非严格模式下标记失败
                        break # 跳出重试
            
            segment_results.append(result)

        self.combine_segments(segment_results, true_audio_duration)
        
        print(f"\n✅ Video composition complete: {self.output_video_path}")