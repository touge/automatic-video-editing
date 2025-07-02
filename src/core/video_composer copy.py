import ffmpeg
import os
import time
import platform
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
            start_time = scene['scene_start']
            end_time = scene['scene_end']
            text = scene['text']

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
        # 直接从配置加载视频参数作为实例属性
        video_config = self.config.get('video', {})
        self.width = video_config.get('width', 1920)
        self.height = video_config.get('height', 1080)
        self.fps = video_config.get('fps', 30)
        self.encoder = video_config.get('encoder', 'libx264')

    def assemble_video(self, scenes: list, scene_asset_paths: list, audio_path: str, subtitle_option: str | None):
        """
        将视频片段和音频合成为最终视频 (使用 ffmpeg-python)。
        - scenes: 场景信息列表，包含 'duration_parts'。
        - scene_asset_paths: 每个场景对应的素材路径列表的列表。
        - audio_path: 音频文件路径。
        - subtitle_option: 字幕选项。如果为 "GENERATE"，则生成新的SRT。如果为文件路径，则使用该文件。如果为None，则不添加字幕。
        """
        output_path = self.task_path / "final_video.mp4"
        print_info("开始使用 ffmpeg-python 合成最终视频...")
        print_info(f"输出文件: {output_path}")
        print_info(f"使用编码器: {self.encoder}")

        # 1. 为每个场景的每个片段创建经过裁剪和标准化的视频流
        video_parts = []
        for i, scene in enumerate(scenes):
            asset_paths = scene_asset_paths[i]
            duration_parts = scene.get('duration_parts', [])
            
            if not asset_paths or len(asset_paths) != len(duration_parts):
                log.warning(f"场景 {i+1} 的素材数量 ({len(asset_paths)}) 与时长分段数量 ({len(duration_parts)}) 不匹配。跳过此场景。")
                continue

            for path, duration in zip(asset_paths, duration_parts):
                stream = ffmpeg.input(path, t=duration)
                video_stream = (
                    stream.video
                    .filter('scale', width=self.width, height=self.height, force_original_aspect_ratio='decrease')
                    .filter('pad', width=self.width, height=self.height, x='(ow-iw)/2', y='(oh-ih)/2', color='black')
                    .filter('fps', fps=self.fps, round='up')
                )
                video_parts.append(video_stream)

        if not video_parts:
            log.error("错误: 没有可用的视频片段来合成。")
            return

        # 2. 拼接所有标准化的视频流
        concatenated_video = ffmpeg.concat(*video_parts, v=1, a=0)
        concatenated_video = concatenated_video.filter('setsar', '1') # 在拼接后应用SAR
        
        # 3. 从提供的音频文件中提取音轨
        original_audio = ffmpeg.input(audio_path).audio

        # 4. 准备最终输出流，根据需要添加字幕滤镜
        video_stream_to_render = concatenated_video
        if subtitle_option: # subtitle_option is not None
            srt_path = None
            if subtitle_option == "GENERATE":
                print_info("正在根据场景数据生成字幕文件...")
                srt_path = self.task_path / "subtitles.srt"
                _scenes_to_srt(scenes, str(srt_path))
            else: # 是一个文件路径
                srt_path = Path(subtitle_option)
            
            if srt_path and srt_path.exists():
                print_info(f"使用字幕文件: {srt_path}")
                escaped_srt_path = _escape_ffmpeg_path(srt_path)
                # 将字幕滤镜应用到复杂的视频流上
                video_stream_to_render = video_stream_to_render.filter('subtitles', filename=escaped_srt_path)
            else:
                log.warning(f"字幕文件 {srt_path} 不存在，将不烧录字幕。")

        # 5. 合并最终视频流与音频
        final_output_args = {
            'vcodec': self.encoder,
            'acodec': 'aac',
            'strict': '-2',
            'loglevel': 'error' # 设置为error，以保持stderr清洁，仅用于捕获真实错误
        }

        # 计算视频总时长，用于进度条
        total_duration = sum(s.get('duration', 0) for s in scenes)

        # 如果总时长无效，则回退到无进度条的原始执行方式
        if total_duration <= 0:
            log.warning("视频总时长无效，无法显示进度。将直接合成...")
            try:
                (ffmpeg.output(video_stream_to_render, original_audio, str(output_path), **final_output_args)
                       .run(overwrite_output=True, quiet=False, capture_stderr=True))
                print_info(f"视频合成完毕，已保存至: {output_path}")
            except ffmpeg.Error as e:
                log.error("ffmpeg 合成视频时出错:", exc_info=True)
                log.error(e.stderr.decode('utf8'))
            return

        # 为ffmpeg指定进度日志文件
        progress_file_path = self.task_path / "ffmpeg_progress.log"
        final_output_args['progress'] = str(progress_file_path)

        try:
            # 异步启动ffmpeg进程
            process = (
                ffmpeg.output(video_stream_to_render, original_audio, str(output_path), **final_output_args)
                .overwrite_output()
                .run_async(pipe_stdout=True, pipe_stderr=True)
            )

            with tqdm(total=round(total_duration, 2), unit="s", desc="视频合成进度") as pbar:
                while process.poll() is None:
                    time.sleep(0.25)
                    if not progress_file_path.exists():
                        continue
                    
                    try:
                        with open(progress_file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        # 从进度日志中解析出已处理的时长
                        progress_data = {line.split('=')[0].strip(): line.split('=')[1].strip() for line in content.strip().split('\n') if '=' in line}
                        processed_time_us = int(progress_data.get('out_time_us', 0))
                        pbar.n = min(round(processed_time_us / 1_000_000, 2), total_duration)
                        pbar.refresh()
                    except (IOError, ValueError, IndexError, KeyError):
                        # 忽略读取或解析过程中的小错误
                        pass
            
            # 等待进程结束并获取输出
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                log.error("\nffmpeg 合成视频时出错:")
                log.error(stderr.decode('utf-8'))
            else:
                print_info(f"\n视频合成完毕，已保存至: {output_path}")

        finally:
            # 确保清理进度日志文件
            if progress_file_path.exists():
                progress_file_path.unlink()