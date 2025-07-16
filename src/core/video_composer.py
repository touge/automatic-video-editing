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
        
        video_config = self.config.get('video', {})
        self.width = video_config.get('width', 1920)
        self.height = video_config.get('height', 1080)
        self.fps = video_config.get('fps', 30)
        
        self.subtitle_config = video_config.get('subtitles', {})
        self.debug = self.config.get('debug', False)

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

    def _run_cmd(self, cmd: list):
        """Executes an ffmpeg command, hiding output unless in debug mode."""
        if self.debug:
            subprocess.run(cmd, check=True)
        else:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _trim_and_normalize_segment(self, src_path: Path, duration: float, dst_path: str, codec_info: tuple):
        codec, extra_args, hwaccel_qsv = codec_info
        vf_string = f"scale={self.width}:-2:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:color=black,fps={self.fps}"

        def try_encode(command, mode_desc):
            try:
                self._run_cmd(command)
                return True
            except CalledProcessError:
                log.warning(f"Failed to process {src_path.name} with '{mode_desc}', trying next.")
                if self.debug:
                    log.debug(f"Failed command: {' '.join(command)}")
                return False

        cmd1 = ['ffmpeg', '-y']
        if hwaccel_qsv:
            cmd1 += ['-hwaccel', 'qsv']
        cmd1 += ['-ss', '0', '-t', str(duration), '-i', str(src_path), '-vf', vf_string, '-c:v', codec, *extra_args, '-c:a', 'aac', dst_path]
        if try_encode(cmd1, f"recommended encoder ({codec})"):
            return

        if codec != 'libx264':
            cmd2 = cmd1.copy()
            try:
                idx = cmd2.index('-c:v')
                del cmd2[idx : idx + 2 + len(extra_args)]
                cmd2.insert(idx, '-c:v'); cmd2.insert(idx + 1, 'libx264'); cmd2.insert(idx + 2, '-preset'); cmd2.insert(idx + 3, 'veryfast')
            except ValueError:
                 cmd2 += ['-c:v', 'libx264', '-preset', 'veryfast']
            if try_encode(cmd2, "software encoder (libx264)"):
                return

        cmd3 = ['ffmpeg', '-y', '-ss', '0', '-t', str(duration), '-i', str(src_path), '-c', 'copy', dst_path]
        if try_encode(cmd3, "stream copy (trim only)"):
            return
        
        print_error(f"Error: Could not process segment {src_path}. All encoding schemes failed. Skipping.")

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

    def _validate_subtitle_config(self):
        font_dir = Path(self.subtitle_config.get('font_dir', 'assets/fonts'))
        if not font_dir.exists():
            log.error(f"Font directory does not exist: {font_dir}")
            return False
        if not any(font_dir.glob('*.?tf')):
            log.error(f"No font files (.ttf, .otf) found in: {font_dir}")
            return False
        return True

    def _burn_subtitles(self, input_path: str, output_path: str, subtitle_path: str):
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

    def assemble_video(self, scenes: list, scene_asset_paths: list, audio_path: str, burn_subtitle: bool = False):
        """组装最终视频"""
        try:
            log.info("--- Starting Video Composition ---")
            
            # 验证输入参数
            if not scenes or not scene_asset_paths:
                raise ValueError("No scenes or asset paths provided")
            if len(scenes) != len(scene_asset_paths):
                raise ValueError(f"Scenes count ({len(scenes)}) doesn't match asset paths count ({len(scene_asset_paths)})")
                
            # 准备视频片段
            log.info(f"--- Preparing {len(scenes)} video segments ---")
            segments = []
            for i, (scene, asset_paths) in enumerate(zip(scenes, scene_asset_paths)):
                try:
                    # 确保至少有一个有效的资源路径
                    if not asset_paths or not isinstance(asset_paths, list):
                        log.error(f"Invalid asset paths for scene {i}: {asset_paths}")
                        continue
                        
                    asset_path = asset_paths[0]  # 使用第一个资源
                    if not os.path.exists(asset_path):
                        log.error(f"Asset file not found: {asset_path}")
                        continue
                        
                    # 获取场景持续时间
                    duration = scene.get('duration', 5.0)
                    
                    # 创建视频片段
                    segment = {
                        'path': asset_path,
                        'duration': duration,
                        'start_time': scene.get('start_time', 0),
                        'scene_text': scene.get('text', ''),
                        'index': i
                    }
                    segments.append(segment)
                    log.debug(f"添加片段 {i}: {asset_path} (duration: {duration}s)")
                    
                except Exception as e:
                    log.error(f"处理片段 {i} 时出错: {str(e)}")
                    continue
                    
            if not segments:
                raise ValueError("No valid video segments could be prepared")
                
            # 处理视频片段
            codec_info = self._detect_video_encoder()
            all_asset_paths = [Path(p) for segment in segments for p in [segment['path']]]
            all_duration_parts = [segment['duration'] for segment in segments]
            total_duration = sum(all_duration_parts)

            print_info(f"--- Preparing {len(all_asset_paths)} video segments ---")
            processed_segments = []
            for i, (src_path, duration) in enumerate(tqdm(zip(all_asset_paths, all_duration_parts), total=len(all_asset_paths), desc="Preparing Segments")):
                dst_path = self.task_manager.get_file_path('video_segment', index=i)
                if not os.path.exists(dst_path):
                    self._trim_and_normalize_segment(src_path, duration, dst_path, codec_info)
                if os.path.exists(dst_path):
                    processed_segments.append(dst_path)

            if not processed_segments:
                print_error("Error: No video segments were successfully processed.")
                return

            print_info("--- Concatenating clean video ---")
            concatenated_video_path = self.task_manager.get_file_path('concatenated_video')
            if not os.path.exists(concatenated_video_path):
                concat_list_path = self.task_manager.get_file_path('concat_list')
                self._make_concat_list(processed_segments, concat_list_path)
                concat_cmd = ['ffmpeg', '-y', '-protocol_whitelist', 'file,concat', '-fflags', '+genpts', '-f', 'concat', '-safe', '0', '-i', concat_list_path, '-c:v', 'copy', concatenated_video_path]
                try:
                    self._run_cmd(concat_cmd)
                except CalledProcessError:
                    log.error("Failed to concatenate clean video.")
                    raise

            print_info("--- Merging audio ---")
            video_with_audio_path = self.task_manager.get_file_path('video_with_audio')
            if not os.path.exists(video_with_audio_path):
                if not os.path.exists(audio_path):
                    log.warning(f"Audio file {audio_path} not found. Final video will be silent.")
                    shutil.copy(concatenated_video_path, video_with_audio_path)
                else:
                    # 移除 -c:v copy 并指定编码器，以确保 -shortest 参数可靠工作
                    codec, extra_args, _ = self._detect_video_encoder()
                    merge_cmd = [
                        'ffmpeg', '-y',
                        '-i', concatenated_video_path,
                        '-i', audio_path,
                        '-c:v', codec, *extra_args,
                        '-c:a', 'aac',
                        '-map', '0:v:0',
                        '-map', '1:a:0',
                        '-shortest',
                        video_with_audio_path
                    ]
                    try:
                        # 使用 ffprobe 获取音频时长，作为进度条的总时长
                        audio_duration = self._get_media_duration(audio_path)
                        if audio_duration is None:
                            # 如果无法获取音频时长，就回退到使用视频总时长
                            log.warning("无法获取音频时长，进度条可能不准确。")
                            audio_duration = total_duration
                        self._run_ffmpeg_with_progress(merge_cmd, audio_duration, "Merging Audio")
                    except CalledProcessError:
                        log.error("Failed to merge audio.")
                        raise

            print_info("--- Generating final video ---")
            final_video_path = self.task_manager.get_file_path('final_video')
            srt_path = self.task_manager.get_file_path('final_srt')
            if burn_subtitle and os.path.exists(srt_path):
                print_info("Burning subtitles...")
                try:
                    self._burn_subtitles(video_with_audio_path, final_video_path, srt_path)
                except Exception as e:
                    log.error(f"Failed to burn subtitles: {e}. Saving non-subtitled version.")
                    shutil.copy(video_with_audio_path, final_video_path)
            else:
                shutil.copy(video_with_audio_path, final_video_path)

            print_success(f"\n✔ Video composition successful! Output: {final_video_path}")
        
        except Exception as e:
            log.error(f"视频合成失败: {str(e)}")
            raise
