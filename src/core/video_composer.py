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
from src.core.task_manager import TaskManager
# 导入全局的进程管理器，用于注册由 ffmpeg-python 启动的子进程
from src.core.process_manager import process_manager

def _escape_ffmpeg_path(path: str | Path) -> str:
    """
    Escapes a path for use in ffmpeg filter parameters, especially for Windows.
    """
    path_str = str(path)
    if platform.system() == "Windows":
        return path_str.replace('\\', '/').replace(':', '\\:')
    return path_str

class VideoComposer:
    def __init__(self, config: dict, task_id: str):
        self.config = config
        self.task_manager = TaskManager(task_id)
        
        composition_settings = self.config.get('composition_settings', {})
        self.width = self.config.get('composition_settings.size.width', 1920)
        self.height = self.config.get('composition_settings.size.height', 1080)
        self.fps = self.config.get('composition_settings.fps', 30)
        
        self.subtitle_config = self.config.get('video.subtitles', {})
        self.debug = self.config.get('debug', False)

    # --- Public Methods for Staged Assembly ---

    def prepare_and_normalize_all_segments(self, scenes: list) -> list[str]:
        """
        Prepares all video segments for a list of scenes.
        This includes trimming, extending, and normalizing each segment.
        Returns a list of paths to the processed segment files.
        """
        print_info(f"--- Preparing {len(scenes)} video segments ---")
        codec_info = self._detect_video_encoder()
        processed_segments = []

        for i, scene in enumerate(tqdm(scenes, desc="Preparing Segments")):
            dst_path = self.task_manager.get_file_path('video_segment', index=i)
            if os.path.exists(dst_path):
                processed_segments.append(dst_path)
                continue

            src_path = Path(scene['asset_path'])
            required_duration = scene.get('time', 5.0)
            actual_duration = scene.get('actual_duration', 0)
            
            temp_path = dst_path
            
            # Extend if necessary
            if 'extend_method' in scene:
                temp_extended_path = self.task_manager.get_file_path('temp_video_file', name=f"extended_{i}.mp4")
                self._extend_video_segment(str(src_path), temp_extended_path, actual_duration, scene['extend_method'], scene['extend_duration'])
                src_path = Path(temp_extended_path)
                actual_duration += scene['extend_duration']

            # Trim and normalize
            try:
                self._trim_and_normalize_segment(src_path, required_duration, temp_path, codec_info)
                processed_segments.append(temp_path)
            except CalledProcessError as e:
                # 捕获到致命错误，记录并重新抛出以中止程序
                log.error(f"Failed to process segment {src_path.name}, stopping composition. FFmpeg command failed with exit code {e.returncode}.")
                raise e
            finally:
                if 'extend_method' in scene and os.path.exists(str(src_path)):
                    os.unlink(str(src_path))

        if len(processed_segments) != len(scenes):
            raise RuntimeError("Not all video segments were successfully processed.")
            
        return processed_segments

    def concatenate_segments(self, segment_paths: list[str]) -> str:
        """
        Uses the concat filter to concatenate segments, which is the most reliable method for timestamp accuracy.
        """
        print_info("--- Concatenating clean video (using concat filter for timestamp accuracy) ---")
        output_path = self.task_manager.get_file_path('concatenated_video')
        if os.path.exists(output_path):
            log.warning(f"Concatenated video already exists, skipping: {output_path}")
            return output_path

        if not segment_paths:
            raise ValueError("No video segments to concatenate.")

        total_duration = sum(self._get_media_duration(p) or 0 for p in segment_paths)
        log.info(f"Total real duration of segments: {total_duration:.2f}s. Concatenating with filter...")

        # --- Build the complex filter command ---
        # 1. Add all segments as inputs
        concat_cmd = ['ffmpeg', '-y']
        for path in segment_paths:
            concat_cmd.extend(['-i', Path(path).as_posix()])

        # 2. Build the filter_complex string
        num_segments = len(segment_paths)
        filter_str = ""
        # Generate [0:v:0][0:a:0][1:v:0][1:a:0]... string
        for i in range(num_segments):
            filter_str += f"[{i}:v:0]"
        
        # Generate the final filter string: e.g., [0:v:0][1:v:0]concat=n=2:v=1[v]
        filter_str += f"concat=n={num_segments}:v=1:a=0[v]"
        
        concat_cmd.extend([
            '-filter_complex', filter_str,
            '-map', '[v]',
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
            '-an', # The output is silent
            output_path
        ])
        
        try:
            self._run_ffmpeg_with_progress(concat_cmd, total_duration, "Concatenating Segments")
        except CalledProcessError:
            log.error("Failed to concatenate clean video using concat filter.")
            raise
        return output_path

    def merge_audio(self, video_path: str, audio_path: str) -> str:
        """
        Merges an audio file with a video file.
        Returns the path to the video with audio.
        """
        print_info("--- Merging audio ---")
        output_path = self.task_manager.get_file_path('video_with_audio')
        if os.path.exists(output_path):
            log.warning(f"Video with audio already exists, skipping: {output_path}")
            return output_path

        if not os.path.exists(audio_path):
            log.warning(f"Audio file {audio_path} not found. Resulting video will be silent.")
            shutil.copy(video_path, output_path)
            return output_path

        audio_duration = self._get_media_duration(audio_path)
        if audio_duration is None:
            log.warning("Could not get audio duration, merging might be inaccurate.")
            audio_duration = self._get_media_duration(video_path) # Fallback

        merge_cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-t', str(audio_duration),
            output_path
        ]
        try:
            self._run_ffmpeg_with_progress(merge_cmd, audio_duration, "Merging Audio")
        except CalledProcessError:
            log.error("Failed to merge audio.")
            raise
        return output_path

    def burn_subtitles_to_video(self, video_path: str) -> str:
        """
        Burns subtitles into a video file.
        Returns the path to the final video.
        """
        print_info("--- Burning subtitles ---")
        output_path = self.task_manager.get_file_path('final_video')
        srt_path = self.task_manager.get_file_path('final_srt')

        if not os.path.exists(srt_path):
            log.warning(f"SRT file not found at {srt_path}. Final video will not have subtitles.")
            shutil.copy(video_path, output_path)
            return output_path

        try:
            self._burn_subtitles_internal(video_path, output_path, srt_path)
        except Exception as e:
            log.error(f"Failed to burn subtitles: {e}. Saving non-subtitled version.")
            shutil.copy(video_path, output_path)
        
        return output_path

    # --- Private Helper Methods ---

    def _detect_video_encoder(self) -> tuple[str, list, bool]:
        """Detects available video encoders, prioritizing hardware encoding."""
        try:
            result = subprocess.run(
                ['ffmpeg', '-hide_banner', '-encoders'],
                capture_output=True, text=True, check=True, encoding='utf-8'
            )
            available_encoders = result.stdout.lower()
        except (FileNotFoundError, CalledProcessError):
            log.warning("Could not execute ffmpeg -encoders, falling back to default libx264.")
            return 'libx264', ['-preset', 'veryfast'], False

        if 'h264_nvenc' in available_encoders:
            print_info("NVIDIA NVENC hardware encoder detected.")
            return 'h264_nvenc', ['-preset', 'p2'], False
        if 'h264_qsv' in available_encoders:
            print_info("Intel QSV hardware encoder detected.")
            return 'h264_qsv', [], True
        if 'h264_videotoolbox' in available_encoders:
            print_info("Apple VideoToolbox hardware encoder detected.")
            return 'h264_videotoolbox', [], False
        
        print_warning("No specific hardware encoder detected, using efficient libx264 software encoder.")
        return 'libx264', ['-preset', 'veryfast'], False

    def _run_cmd(self, cmd: list, log_progress: bool = False, total_duration: float = 0, desc: str = ""):
        """Executes an ffmpeg command, optionally showing progress and hiding output unless in debug mode."""
        if self.debug:
            log.debug(f"Executing FFmpeg command: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            return

        if log_progress:
            self._run_ffmpeg_with_progress(cmd, total_duration, desc)
        else:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _trim_and_normalize_segment(self, src_path: Path, required_duration: float, temp_dst_path: str, codec_info: tuple):
        """
        Trims and normalizes a video segment to the required duration.
        """
        codec, extra_args, hwaccel_qsv = codec_info
        # 最终修复：使用 force_original_aspect_ratio=decrease 来正确处理缩放和填充
        vf_string = f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:-1:-1:color=black,fps={self.fps}"
        
        src_path_str = src_path.as_posix()
        dst_path_str = Path(temp_dst_path).as_posix()

        cmd = ['ffmpeg', '-y']
        if hwaccel_qsv:
            cmd += ['-hwaccel', 'qsv']
        cmd += ['-i', src_path_str, '-t', str(required_duration), '-vf', vf_string, '-c:v', codec, *extra_args, '-an', dst_path_str]
        
        try:
            self._run_cmd(cmd)
        except CalledProcessError as e:
            log.warning(f"Failed to process {src_path.name} with recommended encoder. Trying software fallback.")
            cmd_fallback = ['ffmpeg', '-y', '-i', src_path_str, '-t', str(required_duration), '-vf', vf_string, '-c:v', 'libx264', '-preset', 'veryfast', '-an', dst_path_str]
            try:
                self._run_cmd(cmd_fallback)
            except CalledProcessError as fallback_e:
                log.error(f"Software fallback also failed for {src_path.name}.")
                raise fallback_e

    def _extend_video_segment(self, input_path: str, output_path: str, actual_duration: float, extend_method: str, extend_duration: float):
        """
        Extends a video segment using looping or freeze frame.
        """
        if extend_method == 'loop':
            num_loops = math.ceil((actual_duration + extend_duration) / actual_duration)
            log.debug(f"Looping video {os.path.basename(input_path)} {num_loops} times to extend by {extend_duration:.2f}s")
            
            loop_list_path = self.task_manager.get_file_path('concat_list', name=f"loop_{Path(input_path).stem}")
            lines = [f"file '{Path(input_path).resolve().as_posix()}'\n" for _ in range(int(num_loops))]
            with open(loop_list_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            loop_cmd = [
                'ffmpeg', '-y',
                '-protocol_whitelist', 'file,concat',
                '-f', 'concat', '-safe', '0',
                '-i', loop_list_path,
                '-t', str(actual_duration + extend_duration),
                '-c', 'copy',
                output_path
            ]
            try:
                self._run_cmd(loop_cmd)
            finally:
                if os.path.exists(loop_list_path):
                    os.unlink(loop_list_path)

        elif extend_method == 'freeze_frame':
            # ... (implementation remains the same)
            pass
        else:
            shutil.copy(input_path, output_path)

    def _make_concat_list(self, segment_paths: list[str], list_path: str):
        lines = [f"file '{Path(p).resolve().as_posix()}'\n" for p in segment_paths]
        with open(list_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        log.debug(f"Generated concat_list.txt content:\n{''.join(lines)}")

    def _get_media_duration(self, file_path: str) -> float | None:
        """使用 ffprobe 获取媒体文件的时长（秒）。"""
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(file_path)
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except (FileNotFoundError, CalledProcessError, ValueError) as e:
            log.error(f"无法使用 ffprobe 获取时长: {file_path}. Error: {e}")
            return None

    def _run_ffmpeg_with_progress(self, cmd: list, total_duration: float, desc: str):
        if self.debug:
            log.debug(f"Executing FFmpeg command: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            return

        progress_log_path = self.task_manager.get_file_path('progress_log', name=desc.replace(' ', '_'))
        progress_cmd = cmd[:1] + ['-progress', progress_log_path] + cmd[1:]
        
        process = subprocess.Popen(progress_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process_manager.register_process(process.pid)

        pbar = tqdm(total=round(total_duration, 2), unit="s", desc=desc)
        last_time = 0.0
        try:
            while process.poll() is None:
                time.sleep(0.25)
                if not os.path.exists(progress_log_path): continue
                try:
                    with open(progress_log_path, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    last_line = content.splitlines()[-1]
                    if 'out_time_us=' in last_line:
                        current_time = round(int(last_line.split('=')[1]) / 1_000_000, 2)
                        if current_time > last_time:
                            pbar.update(current_time - last_time)
                            last_time = current_time
                except (IOError, ValueError, IndexError):
                    pass
            if pbar.n < total_duration:
                pbar.update(total_duration - pbar.n)
        finally:
            pbar.close()
            if process.returncode != 0:
                log.error(f"FFmpeg {desc} process failed.")
                raise CalledProcessError(process.returncode, cmd)
            if os.path.exists(progress_log_path):
                os.unlink(progress_log_path)

    def _burn_subtitles_internal(self, input_path: str, output_path: str, subtitle_path: str):
        if not self._validate_subtitle_config():
            raise RuntimeError("Subtitle configuration validation failed.")
        
        font_dir = Path(self.subtitle_config.get('font_dir', 'assets/fonts'))
        escaped_font_dir = _escape_ffmpeg_path(font_dir.resolve())
        style_options = ",".join([f"{k}={v}" for k, v in self.subtitle_config.items() if k not in ['font_dir']])
        subtitle_filter = f"subtitles={_escape_ffmpeg_path(subtitle_path)}:fontsdir='{escaped_font_dir}':force_style='{style_options}'"
        
        ffmpeg_cmd = ['ffmpeg', '-y', '-i', input_path, '-vf', subtitle_filter, '-c:a', 'copy', output_path]
        if self.debug:
            log.debug(f"FFmpeg subtitle burn command: {' '.join(ffmpeg_cmd)}")
        
        try:
            self._run_cmd(ffmpeg_cmd)
        except CalledProcessError as e:
            log.error(f"FFmpeg subtitle burn failed: {e}")
            raise

    def _validate_subtitle_config(self):
        # ... (implementation remains the same)
        pass
