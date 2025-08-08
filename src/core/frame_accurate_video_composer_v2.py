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
        :param max_workers: 获取素材时长的线程数
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
            result = subprocess.run(
                ["ffmpeg", "-encoders"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                check=True
            )
            if "h264_nvenc" in result.stdout:
                print("\n✅ 检测到 NVIDIA GPU 加速支持 (h264_nvenc)，将启用硬件加速。")
                return True
            else:
                print("\nℹ️ 未检测到 NVIDIA GPU 加速支持，将使用 CPU 进行编码。")
                return False
        except FileNotFoundError:
            print("\n⚠️ FFmpeg 未安装或不在系统路径中，无法使用 GPU 加速。")
            return False
        except subprocess.CalledProcessError:
            print("\n⚠️ 调用 FFmpeg 失败，无法检查 GPU 支持。")
            return False
        except Exception as e:
            print(f"\n⚠️ 检查 GPU 支持时发生未知错误: {e}")
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
            output = subprocess.check_output(cmd).decode().strip()
            return float(output)
        except Exception:
            return 0.0

    def process_segment(self, segment, seg_index):
        """🎬 基于帧数分配段落时长，生成段落视频，确保零误差"""
        scenes = segment.get("scenes", [])

        if not scenes:
            raise ValueError(f"Data integrity error: Segment {seg_index:02d} contains no scenes. Processing cannot continue.")

        target_duration = segment["duration"]
        asset_paths = [scene["asset_path"] for scene in scenes]

        for i, scene in enumerate(scenes):
            if "time" not in scene or not isinstance(scene["time"], (int, float)) or scene["time"] <= 0:
                raise ValueError(f"❌ Scene {i} 缺少有效的 'time' 字段 → {scene.get('asset_path')}")

        target_total_frames = int(round(target_duration * self.fps))
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            real_durations = list(tqdm(executor.map(self.get_duration, asset_paths),
                                    total=len(scenes),
                                    desc=f"⏱️ 获取素材 Segment{seg_index:02d}"))
        for scene, real_dur in zip(scenes, real_durations):
            scene["real_duration"] = real_dur

        total_time_ratio = sum(scene["time"] for scene in scenes)
        allocated_frames_sum = 0
        for i, scene in enumerate(scenes):
            if i == len(scenes) - 1:
                scene["allocated_frames"] = target_total_frames - allocated_frames_sum
            else:
                ratio = scene["time"] / total_time_ratio
                frames = int(round(ratio * target_total_frames))
                scene["allocated_frames"] = frames
                allocated_frames_sum += frames
        
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
            print(f"🎞️ {basename(scene['asset_path'])} → 原{origin}s,补{compensated}s,计:{allocated:.3f}s ({frames}帧)")

        filter_complex = "".join(filter_lines)
        filter_complex += f"{''.join(concat_labels)}concat=n={len(scenes)}:v=1:a=0[outv]"

        output_path = self.temp_dir / f"segment_{seg_index:02d}.mp4"

        if output_path.exists() and output_path.stat().st_size > 1024:
            print(f"✅ Segment {seg_index:02d} 已存在，跳过生成。")
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

        subprocess.run(
            ffmpeg_cmd,
            stdout=subprocess.DEVNULL if self.silent else None,
            stderr=subprocess.DEVNULL if self.silent else None
        )

        if not output_path.exists() or output_path.stat().st_size < 1024:
            print(f"\n🧨 Segment {seg_index:02d} 生成失败 → {output_path}")
            for path in asset_paths:
                print(f"  📄 来源素材：{path}")
            if self.strict_mode:
                raise RuntimeError(f"❌ 严格模式终止：Segment {seg_index:02d} 视频生成失败")
            return None
        
        real_output_duration = self.get_duration(output_path)
        real_output_frames = int(round(real_output_duration * self.fps))
        frame_diff = real_output_frames - target_total_frames
        
        planned_duration_str = f"{target_total_frames / self.fps:.3f}s"
        real_duration_str = f"{real_output_duration:.3f}s"
        
        print(f"📊 Segment{seg_index:02d} 计划 {target_total_frames}帧 ({planned_duration_str})，"
              f"合成 {real_output_frames}帧 ({real_duration_str})，"
              f"误差 {frame_diff:+}帧\n")

        return (output_path, target_total_frames)

    def _test_scene_combination(self, scenes_to_test: list, output_filename: str) -> bool:
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

        result = subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8')

        if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1024:
            log.debug(f"测试合并失败。FFmpeg stderr:\n{result.stderr}")
            if output_path.exists():
                os.remove(output_path)
            return False
        
        if output_path.exists():
            os.remove(output_path)
        return True

    def _replace_asset_for_scene(self, scene: dict) -> bool:
        log.info(f"  -> 正在为场景替换素材: {scene.get('asset_path')}")
        try:
            asset_manager = AssetManager(config, self.task_id)
            online_search_count = config.get('asset_search', {}).get('online_search_count', 10)
        except Exception as e:
            log.error(f"  -> 替换失败：初始化 AssetManager 失败。错误: {e}")
            return False

        old_asset_path = scene.get('asset_path')
        found_video_info_list = asset_manager.find_assets_for_scene(scene, online_search_count)
        
        if not found_video_info_list:
            log.error(f"  -> 未能找到替换素材。")
            return False

        new_asset_path = found_video_info_list[0].get('local_path')
        if not new_asset_path or not os.path.exists(new_asset_path):
            log.error(f"  -> AssetManager 返回了无效的新素材路径。")
            return False

        try:
            if os.path.exists(old_asset_path):
                os.remove(old_asset_path)
            shutil.move(new_asset_path, old_asset_path)
            log.success(f"  -> 成功将新素材 '{new_asset_path}' 替换到 '{old_asset_path}'")
            return True
        except Exception as e:
            log.error(f"  -> 文件替换操作失败: {e}")
            return False

    def _handle_segment_failure(self, segment: dict, seg_index: int) -> bool:
        log.warning(f"进入诊断恢复模式：处理失败的 Segment {seg_index}...")
        scenes = segment.get("scenes", [])
        if len(scenes) <= 1:
            log.warning("片段只包含一个或零个场景，直接尝试替换。")
            if scenes and self._replace_asset_for_scene(scenes[0]):
                return True
            return False

        while True:
            good_scenes = []
            found_faulty = False
            for i, scene in enumerate(scenes):
                log.info(f"  -> 诊断测试: 正在合并场景 {i+1}/{len(scenes)}...")
                test_combination = good_scenes + [scene]
                
                if not self._test_scene_combination(test_combination, f"diag_test_{seg_index}.mp4"):
                    log.error(f"  -> 定位到问题素材: 场景 {i} ({scene.get('asset_path')})")
                    found_faulty = True
                    
                    if not self._replace_asset_for_scene(scene):
                        log.error("  -> 替换素材失败，终止此片段的恢复流程。")
                        return False
                    
                    log.info("  -> 素材替换成功，将从头开始重新验证整个片段的兼容性。")
                    break
                else:
                    good_scenes.append(scene)
            
            if not found_faulty:
                log.success(f"诊断完成：Segment {seg_index} 中的所有素材均兼容，恢复成功。")
                return True

    def combine_segments(self, segment_results, audio_duration):
        """📽️ V2: 使用 concat 滤镜合并所有段落，并用 tpad 滤镜确保视频与音频同长"""
        valid_segment_results = [r for r in segment_results if r and r[0] and r[0].exists() and r[0].stat().st_size > 1024]
        if not valid_segment_results:
            raise RuntimeError("❌ 无可用段落可合并")

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
            log.warning(f"📹 视频总时长 ({total_video_duration:.3f}s) 短于音频 ({audio_duration:.3f}s)，将填充 {padding_duration:.3f}s 黑场。")
            # 使用 tpad 滤镜在视频末尾添加黑色帧来补足时长
            filter_complex_parts.append(f"[v_concat]tpad=stop_duration={audio_duration}:color=black[v_padded];")
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
            "-c:v", "libx264", # 视频需要重新编码
            "-crf", "23",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(audio_duration), # V2.1 修正: 使用 -t 精确控制时长
            "-y", str(self.output_video_path)
        ]
        
        if self.gpu_enabled:
            ffmpeg_cmd[ffmpeg_cmd.index("-c:v") + 1] = "h264_nvenc"
            ffmpeg_cmd[ffmpeg_cmd.index("-preset") + 1] = "p7"
            ffmpeg_cmd.insert(ffmpeg_cmd.index("h264_nvenc") + 1, "-cq")
            ffmpeg_cmd.insert(ffmpeg_cmd.index("-cq") + 1, "23")


        print("\n🔗 正在使用 V2 滤镜链合并所有段落...")
        # 使用 Popen 实时打印 FFmpeg 日志，并确保消耗输出以避免死锁
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            bufsize=1
        )
        
        # 必须消耗 stdout 来防止缓冲区填满导致的死锁
        for line in iter(process.stdout.readline, ''):
            if not self.silent:
                print(line, end='')
        
        return_code = process.wait()
        if return_code != 0:
            log.error(f"FFmpeg 合并过程失败，返回码: {return_code}")
        
        if self.output_video_path.exists() and self.output_video_path.stat().st_size > 0:
            final_video_duration = self.get_duration(self.output_video_path)
            duration_diff = final_video_duration - audio_duration
            
            print(f"\n✅ 最终校验 (V2):\n"
                  f"  - 目标音频时长: {audio_duration:.3f}s\n"
                  f"  - 最终视频时长: {final_video_duration:.3f}s\n"
                  f"  - 时长差异: {duration_diff:+.3f}s")


    def execute(self):
        """🏁 V2 执行流程: 移除错误的视频时长对齐逻辑"""
        self.load_structure()
        self.temp_dir.mkdir(exist_ok=True)

        true_audio_duration = self.get_duration(self.input_audio_path)
        log.info(f"🔊 目标音频时长为: {true_audio_duration:.3f}s")

        # V2 修正: 移除在 execute 方法中修改视频结构的行为。
        # 时长对齐应在最终合并时处理，而不是通过修改片段时长。
        total_planned_video_duration = sum(seg["duration"] for seg in self.structure)
        log.info(f"🎞️ 计划视频总时长为: {total_planned_video_duration:.3f}s")

        segment_results = []
        max_retries = 1
        print(f"\n🎞️ 共 {len(self.structure)} 个视频段落待处理")
        for i, segment in enumerate(self.structure):
            print(f"\n🎬 正在处理 Segment {i+1}/{len(self.structure)}")
            
            result = None
            for attempt in range(max_retries + 1):
                try:
                    result = self.process_segment(segment, i)
                    break
                except RuntimeError as e:
                    log.error(f"生成 Segment {i} 失败 (尝试 {attempt + 1}/{max_retries + 1})。错误: {e}")
                    if attempt < max_retries:
                        recovery_successful = self._handle_segment_failure(segment, i)
                        if recovery_successful:
                            log.success(f"恢复成功，正在重试 Segment {i}...")
                            continue
                        else:
                            log.error(f"恢复失败，终止 Segment {i} 的处理。")
                            raise e
                    else:
                        log.error(f"已达到最大重试次数，Segment {i} 彻底失败。")
                        raise e
            
            segment_results.append(result)

        self.combine_segments(segment_results, true_audio_duration)
        
        print(f"\n✅ 成片完成：{self.output_video_path}")
