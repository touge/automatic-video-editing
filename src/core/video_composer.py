import os
import sys
import time
import platform
import subprocess
from subprocess import CalledProcessError
import shutil
from pathlib import Path
from tqdm import tqdm
from src.logger import log
from src.color_utils import (
    print_colored,
    print_error,
    print_warning,
    print_success,
    print_info,
)

def _escape_ffmpeg_path(path: str | Path) -> str:
    """
    为在ffmpeg滤镜参数中使用的路径进行转义，尤其针对Windows。
    参考: https://github.com/kkroening/ffmpeg-python/issues/269
    """
    path_str = str(path)
    if platform.system() == "Windows":
        return path_str.replace('\\', '/').replace(':', '\\:')
    return path_str

def _scenes_to_srt(scenes: list, srt_path: str):
    """将场景数据转换为SRT字幕文件"""
    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, scene in enumerate(scenes):
            # 使用场景分割时确定的精确起止时间
            start_time = scene.get('scene_start', 0)
            end_time = scene.get('scene_end', 0)
            text = scene['text']

            if end_time <= start_time:
                continue

            start_h, rem = divmod(start_time, 3600)
            start_m, rem = divmod(rem, 60)
            start_s, start_ms = divmod(rem, 1)

            end_h, rem = divmod(end_time, 3600)
            end_m, rem = divmod(rem, 60)
            end_s, end_ms = divmod(rem, 1)

            f.write(f"{i + 1}\n")
            f.write(f"{int(start_h):02}:{int(start_m):02}:{int(start_s):02},{int(start_ms*1000):03} --> "
                    f"{int(end_h):02}:{int(end_m):02}:{int(end_s):02},{int(end_ms*1000):03}\n")
            f.write(f"{text}\n\n")

class VideoComposer:
    def __init__(self, config: dict, task_id: str):
        self.config = config
        self.task_id = task_id
        self.task_path = Path("storage") / "tasks" / task_id
        
        video_config = self.config.get('video', {})
        self.width = video_config.get('width', 1920)
        self.height = video_config.get('height', 1080)
        self.fps = video_config.get('fps', 30)
        
        # 加载字幕配置
        self.subtitle_config = video_config.get('subtitles', {})
        
        # 调试模式，用于在执行ffmpeg命令时打印详细日志
        self.debug = self.config.get('debug', False)

        # 为每个阶段的产出物（缓存）创建一个目录
        self.cache_path = self.task_path / "cache"
        self.cache_path.mkdir(parents=True, exist_ok=True)

    def _detect_video_encoder(self) -> tuple[str, list, bool]:
        """检测可用的视频编码器，优先硬件编码。返回 (codec, extra_args, hwaccel_qsv)"""
        try:
            # 运行 ffmpeg -encoders 命令并捕获输出
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True, text=True, check=True, encoding='utf-8'
            )
            available_encoders = result.stdout.lower()
        except (FileNotFoundError, CalledProcessError):
            log.warning("无法执行 ffmpeg -encoders，将回退到默认的 libx264 编码器。")
            return 'libx264', ['-preset', 'veryfast'], False

        # 按优先级检查硬件编码器
        if 'h264_nvenc' in available_encoders:
            print_info("检测到 NVIDIA NVENC 硬件编码器。")
            return 'h264_nvenc', ['-preset', 'p2'], False
        if 'h264_qsv' in available_encoders:
            print_info("检测到 Intel QSV 硬件编码器。")
            return 'h264_qsv', [], True
        if 'h264_videotoolbox' in available_encoders:
            print_info("检测到 Apple VideoToolbox 硬件编码器。")
            return 'h264_videotoolbox', [], False
        
        print_warning("未检测到特定硬件编码器，将使用高效的 libx264 软件编码器。")
        return 'libx264', ['-preset', 'veryfast'], False

    def _run_cmd(self, cmd: list):
        """执行ffmpeg命令，根据debug模式决定是否隐藏输出"""
        if self.debug:
            # 调试模式下，实时打印所有输出
            subprocess.run(cmd, check=True)
        else:
            # 非调试模式下，抑制标准输出和错误流，只在失败时抛出异常
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _trim_and_normalize_segment(self, src_path: Path, duration: float, dst_path: Path, codec_info: tuple):
        """
        裁剪并标准化单个视频片段，具有强大的编码回退机制。
        - src_path: 源视频文件路径。
        - duration: 需要从视频开头裁剪的时长。
        - dst_path: 处理后输出的片段路径。
        - codec_info: 包含(编码器, 额外参数, 是否为QSV硬件加速)的元组。
        """
        codec, extra_args, hwaccel_qsv = codec_info
        
        # 定义视频滤镜链：缩放、填充黑边、设定帧率
        vf_string = (
            f"scale={self.width}:-2:force_original_aspect_ratio=decrease,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={self.fps}"
        )

        # 内部函数，用于尝试执行一个ffmpeg命令
        def try_encode(command, mode_desc):
            try:
                self._run_cmd(command)
                return True
            except CalledProcessError:
                log.warning(f"使用“{mode_desc}”模式处理 {src_path.name} 失败，尝试下一个方案...")
                if self.debug:
                    log.debug(f"失败的命令: {' '.join(command)}")
                return False

        # 方案 1: 使用推荐的编码器（可能是硬件编码）进行转码
        cmd1 = ['ffmpeg', '-y']
        if hwaccel_qsv:
            cmd1 += ['-hwaccel', 'qsv']
        cmd1 += [
            '-ss', '0', '-t', str(duration),
            '-i', str(src_path),
            '-vf', vf_string,
            '-c:v', codec, *extra_args,
            '-c:a', 'aac', str(dst_path)
        ]
        if try_encode(cmd1, f"推荐编码器 ({codec})"):
            return

        # 方案 2: 如果推荐编码器不是 libx264 且失败了，回退到 libx264
        if codec != 'libx264':
            cmd2 = cmd1.copy()
            # 找到并替换视频编码器相关参数
            try:
                idx = cmd2.index('-c:v')
                # 移除旧的编码器和其特定参数
                del cmd2[idx : idx + 2 + len(extra_args)]
                # 插入 libx264 和它的参数
                cmd2.insert(idx, '-c:v')
                cmd2.insert(idx + 1, 'libx264')
                cmd2.insert(idx + 2, '-preset')
                cmd2.insert(idx + 3, 'veryfast')
            except ValueError: # 如果-c:v找不到，直接在末尾添加
                 cmd2 += ['-c:v', 'libx264', '-preset', 'veryfast']

            if try_encode(cmd2, "软件编码器 (libx264)"):
                return

        # 方案 3: 作为最后手段，尝试流拷贝（不应用任何视频滤镜，只做裁剪）
        # 这在源视频格式与目标高度兼容时可能成功
        cmd3 = [
            'ffmpeg', '-y',
            '-ss', '0', '-t', str(duration),
            '-i', str(src_path),
            '-c', 'copy',
            str(dst_path)
        ]
        if try_encode(cmd3, "流拷贝 (仅裁剪)"):
            return
        
        # 如果所有方案都失败了
        print_error(f"错误: 无法处理片段 {src_path}，所有编码方案均告失败。该片段将被跳过。")

    # def _make_concat_list(self, segment_paths: list[Path], list_path: Path):
    #     """为ffmpeg的concat demuxer创建文件列表。"""
    #     with list_path.open('w', encoding='utf-8') as f:
    #         for seg_path in segment_paths:
    #             # 使用 as_posix() 确保路径在所有系统上都使用正斜杠
    #             f.write(f"file '{seg_path.as_posix()}'\n")
    def _make_concat_list(self, segment_paths: list[Path], list_path: Path):
        """为 ffmpeg 的 concat demuxer 创建文件列表。"""
        lines = []
        for seg_path in segment_paths:
            abs_path = seg_path.resolve().as_posix()
            lines.append(f"file '{abs_path}'\n")

        # 写入文件
        with list_path.open('w', encoding='utf-8') as f:
            f.writelines(lines)

        # 打印校验
        log.debug(f"生成的 concat_list.txt 内容：\n{''.join(lines)}")


    def _run_ffmpeg_with_progress(self, cmd: list, total_duration: float, desc: str):
        """通用函数，用于带进度条地运行ffmpeg命令。"""
        if self.debug:
            log.debug(f"执行FFmpeg命令: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            return

        progress_log_path = self.cache_path / f"progress_{desc.replace(' ', '_')}.log"
        
        # 在命令中插入 -progress 参数
        progress_cmd = cmd[:1] + ['-progress', str(progress_log_path)] + cmd[1:]
        
        process = subprocess.Popen(progress_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        pbar = tqdm(total=round(total_duration, 2), unit="s", desc=desc)
        last_time = 0.0
        try:
            while process.poll() is None:
                time.sleep(0.25)
                if not progress_log_path.exists():
                    continue
                
                try:
                    # 读取日志文件的最后几行来获取最新进度
                    with open(progress_log_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    
                    # 解析 out_time_us
                    last_line = content.splitlines()[-1]
                    if 'out_time_us=' in last_line:
                        processed_time_us = int(last_line.split('=')[1])
                        current_time = round(processed_time_us / 1_000_000, 2)
                        if current_time > last_time:
                            pbar.update(current_time - last_time)
                            last_time = current_time
                except (IOError, ValueError, IndexError):
                    # 忽略读取或解析过程中的小错误
                    pass
            
            # 确保进度条走完
            if pbar.n < total_duration:
                pbar.update(total_duration - pbar.n)

        finally:
            pbar.close()
            if process.returncode != 0:
                log.error(f"FFmpeg {desc} 过程失败。")
                # 在调试模式下可以考虑保留日志文件
                # if not self.debug and progress_log_path.exists():
                #     progress_log_path.unlink()
                raise CalledProcessError(process.returncode, cmd)
            
            if progress_log_path.exists():
                progress_log_path.unlink()

    def assemble_video(self, scenes: list, scene_asset_paths: list, audio_path: str, subtitle_option: str | None):
        """
        采用分阶段、多级缓存的策略，将视频片段和音频合成为最终视频。
        """
        print_info("--- 开始视频合成流程 ---")
        final_video_path = self.task_path / "final_video.mp4"

        # --- 阶段 1/5: 准备工作 ---
        print_info("--- 阶段 1/5: 准备工作与素材检查 ---")
        codec, extra_args, hwaccel_qsv = self._detect_video_encoder()
        codec_info = (codec, extra_args, hwaccel_qsv)

        all_asset_paths = [Path(p) for paths in scene_asset_paths for p in paths]
        all_duration_parts = [dur for s in scenes for dur in s.get('duration_parts', [])]
        total_duration = sum(all_duration_parts)

        if not all_asset_paths:
            log.error("错误: 没有可用的视频素材路径。")
            return

        # --- 阶段 2/5: 准备视频片段 ---
        print_info(f"--- 阶段 2/5: 检查并准备 {len(all_asset_paths)} 个视频片段 ---")
        processed_segments = []
        all_segments_cached = True
        with tqdm(total=len(all_asset_paths), desc="准备片段", unit="个") as pbar:
            for i, (src_path, duration) in enumerate(zip(all_asset_paths, all_duration_parts)):
                dst_path = self.cache_path / f"seg_{i:04d}.mp4"
                if not dst_path.exists():
                    all_segments_cached = False
                    self._trim_and_normalize_segment(src_path, duration, dst_path, codec_info)

                if dst_path.exists():
                    processed_segments.append(dst_path)
                pbar.update(1)

        if all_segments_cached:
            print_info("所有视频片段均已从缓存加载。")

        if not processed_segments:
            log.error("错误: 未能成功处理任何视频片段，无法继续合成。")
            return

        # --- 阶段 3/5: 拼接纯净视频 (无声、无字幕) ---
        print_info("--- 阶段 3/5: 拼接纯净视频 ---")
        concatenated_video_path = self.cache_path / "video_only_concatenated.mp4"
        if concatenated_video_path.exists():
            print_info(f"发现已缓存的拼接视频 ({concatenated_video_path.name})，跳过拼接步骤。")
        else:
            concat_list_path = self.cache_path / "concat_list.txt"
            self._make_concat_list(processed_segments, concat_list_path)

            # 由于所有片段都已标准化，我们可以安全地使用流拷贝，这非常快
            concat_cmd = [
                'ffmpeg', '-y',
                '-protocol_whitelist', 'file,concat',
                '-fflags', '+genpts',
                '-f', 'concat', '-safe', '0',
                '-i', str(concat_list_path.resolve()),
                '-c:v', 'copy',
                str(concatenated_video_path)
            ]
            try:
                print_info("正在拼接视频片段...")
                self._run_cmd(concat_cmd)
                print_success("纯净视频拼接完成。")
            except CalledProcessError:
                log.error("拼接纯净视频失败，程序终止。")
                return

        # --- 阶段 4/5: 合并音频 ---
        print_info("--- 阶段 4/5: 合并背景音频 ---")
        video_with_audio_path = self.cache_path / "video_with_audio.mp4"
        audio_file_path = Path(audio_path)

        if video_with_audio_path.exists():
            print_info(f"发现已缓存的带音频视频 ({video_with_audio_path.name})，跳过音频合并。")
        elif not audio_file_path.exists():
            log.warning(f"音频文件 {audio_path} 未找到，将跳过音频合并。最终视频将是无声的。")
            shutil.copy(str(concatenated_video_path), str(video_with_audio_path))
        else:
            merge_cmd = [
                'ffmpeg', '-y',
                '-i', str(concatenated_video_path),
                '-i', str(audio_file_path),
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-shortest',
                str(video_with_audio_path)
            ]
            try:
                self._run_ffmpeg_with_progress(merge_cmd, total_duration, "合并音频")
                print_success("音频合并完成。")
            except CalledProcessError:
                log.error("音频合并失败，程序终止。")
                return

        # --- 阶段 5/5: 烧录字幕并生成最终视频 ---
        print_info("--- 阶段 5/5: 生成最终视频 ---")
        srt_path = None
        if subtitle_option:
            if subtitle_option == "GENERATE":
                print_info("根据场景数据生成字幕文件...")
                srt_path = self.cache_path / "subtitles.srt"
                _scenes_to_srt(scenes, str(srt_path))
            else:
                srt_path_obj = Path(subtitle_option)
                if srt_path_obj.exists():
                    srt_path = self.cache_path / srt_path_obj.name
                    shutil.copy(srt_path_obj, srt_path)
                else:
                    log.warning(f"指定的字幕文件 {subtitle_option} 未找到，将不添加字幕。")

        if srt_path:
            print_info("正在烧录字幕...")
            escaped_srt_path = _escape_ffmpeg_path(srt_path)

            subtitle_filter_parts = [f"subtitles={escaped_srt_path}"]
            font_dir = self.subtitle_config.get('font_dir')
            if font_dir and os.path.isdir(font_dir):
                escaped_font_dir = _escape_ffmpeg_path(Path(font_dir).resolve())
                subtitle_filter_parts.append(f"fontsdir='{escaped_font_dir}'")

            style_mapping = {
                'font_name': 'FontName', 'font_size': 'FontSize',
                'primary_color': 'PrimaryColour', 'outline_color': 'OutlineColour',
                'border_style': 'BorderStyle', 'outline': 'Outline', 'shadow': 'Shadow', 'spacing': 'Spacing',
                'alignment': 'Alignment', 'vertical_margin': 'MarginV',
            }
            style_options = [f"{style_key}={value}" for config_key, style_key in style_mapping.items() if (value := self.subtitle_config.get(config_key)) is not None]

            if style_options:
                subtitle_filter_parts.append(f"force_style='{','.join(style_options)}'")

            final_filter_string = ':'.join(subtitle_filter_parts)

            final_cmd = [
                'ffmpeg', '-y',
                '-i', str(video_with_audio_path),
                '-vf', final_filter_string,
                '-c:v', codec, *extra_args,
                '-c:a', 'copy',
                str(final_video_path)
            ]
            try:
                self._run_ffmpeg_with_progress(final_cmd, total_duration, "烧录字幕")
            except CalledProcessError:
                log.error("烧录字幕失败，程序终止。")
                return
        else:
            print_info("无需烧录字幕，直接复制文件...")
            shutil.copy(str(video_with_audio_path), str(final_video_path))

        print_success("\n############################################################")
        print_success(f"✔ 视频合成成功！")
        print_success(f"==> 输出文件位于: {final_video_path}")
        print_success("############################################################")
