import os
from src.config_loader import config
from src.logger import log
from src.core.task_manager import TaskManager
from src.utils import run_command, to_slash_path
import platform
from pathlib import Path

# def _escape_ffmpeg_path(path: str | Path) -> str:
#     """
#     Escapes a path for use in ffmpeg filter parameters, especially for Windows.
#     """
#     path_str = str(path)
#     if platform.system() == "Windows":
#         return path_str.replace('\\', '/').replace(':', '\\:')
#     return path_str

class SubtitleBurner:
    def __init__(self, task_id: str):
        if not task_id:
            raise ValueError("A task_id must be provided.")
        
        self.task_manager = TaskManager(task_id)
        self.config = config
        self.subtitle_config = self.config.get('composition_settings', {}).get('subtitles', {})

    def burn_subtitles(self, video_path: str, srt_path: str, output_path: str) -> str:
        log.info(f"--- Starting Subtitle Burn for Task ID: {self.task_manager.task_id} ---")
        log.info(f"Input video: {video_path}")
        log.info(f"Input SRT: {srt_path}")
        log.info(f"Output video: {to_slash_path(output_path)}")

        try:
            self._burn_subtitles_internal(video_path, output_path, srt_path)
            log.success(f"Video with subtitles created successfully at: {output_path}")
            return output_path
        except Exception as e:
            log.error(f"Failed to burn subtitles: {e}", exc_info=True)
            raise

    # self, input_path: str, output_path: str, subtitle_path: str
    def _burn_subtitles_internal(self, input_path: str, output_path: str, subtitle_path: str):
        if not self._validate_subtitle_config():
            raise RuntimeError("Subtitle configuration validation failed.")

        # 样式映射表
        style_key_map = {
            'font_name': 'FontName',
            'font_size': 'FontSize',
            'primary_color': 'PrimaryColour',
            'outline_color': 'OutlineColour',
            'border_style': 'BorderStyle',
            'outline': 'Outline',
            'shadow': 'Shadow',
            'spacing': 'Spacing',
            'alignment': 'Alignment',
            'vertical_margin': 'MarginV'
        }

        # 构造 force_style 参数
        style_options_list = []
        for config_key, style_value in self.subtitle_config.items():
            if config_key in style_key_map:
                ass_style_key = style_key_map[config_key]
                style_options_list.append(f"{ass_style_key}={style_value}")
        style_options = ",".join(style_options_list)

        # 字体目录
        font_dir = self.subtitle_config.get('font_dir', 'assets/fonts')

        # 路径转义，防止引号或空格炸掉 FFmpeg
        subtitle_path_escaped = subtitle_path.replace("'", r"'\''")
        font_dir_escaped = font_dir.replace("'", r"'\''")

        # 构造字幕滤镜
        subtitle_filter = (
            f"subtitles='{subtitle_path_escaped}':"
            f"fontsdir='{font_dir_escaped}':"
            f"force_style='{style_options}'"
        )

        # 日志等级
        is_debug_mode = self.config.get('debug', False)
        log_level = 'verbose' if is_debug_mode else 'error'

        # 构造 FFmpeg 命令
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-sub_charenc', 'UTF-8',  # 强制字幕编码为 UTF-8
            '-i', input_path,
            '-vf', subtitle_filter,
            '-c:a', 'copy',
            '-loglevel', log_level,
            to_slash_path(output_path)
        ]

        if is_debug_mode:
            log.debug(f"FFmpeg Command: {' '.join(ffmpeg_cmd)}")

        # 执行命令
        try:
            run_command(ffmpeg_cmd, "Failed to burn subtitles")
        except RuntimeError as e:
            log.error(f"FFmpeg execution failed: {e}")
            raise


    def _burn_subtitles_internalx(self, input_path: str, output_path: str, subtitle_path: str):
        if not self._validate_subtitle_config():
            raise RuntimeError("Subtitle configuration validation failed.")

        style_key_map = {
            'font_name': 'FontName',
            'font_size': 'FontSize',
            'primary_color': 'PrimaryColour',
            'outline_color': 'OutlineColour',
            'border_style': 'BorderStyle',
            'outline': 'Outline',
            'shadow': 'Shadow',
            'spacing': 'Spacing',
            'alignment': 'Alignment',
            'vertical_margin': 'MarginV'
        }
        
        style_options_list = []
        for config_key, style_value in self.subtitle_config.items():
            if config_key in style_key_map:
                ass_style_key = style_key_map[config_key]
                style_options_list.append(f"{ass_style_key}={style_value}")
        style_options = ",".join(style_options_list)

        font_dir = self.subtitle_config.get('font_dir', 'assets/fonts')
        subtitle_filter = (
            f"subtitles={subtitle_path}"
            f":fontsdir='{font_dir}'"
            f":force_style='{style_options}'"
        )

        is_debug_mode = self.config.get('debug', False)
        log_level = 'verbose' if is_debug_mode else 'error'

        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-vf', subtitle_filter,
            '-c:a', 'copy',
            '-loglevel', log_level,
            to_slash_path(output_path)
        ]

        if is_debug_mode:
            log.debug(f"FFmpeg Command: {' '.join(ffmpeg_cmd)}")

        try:
            run_command(ffmpeg_cmd, "Failed to burn subtitles")
        except RuntimeError as e:
            log.error(f"FFmpeg execution failed: {e}")
            raise

    def _validate_subtitle_config(self) -> bool:
        if not self.subtitle_config:
            log.warning("Subtitle configuration is missing.")
            return False

        font_dir = self.subtitle_config.get('font_dir')
        if not font_dir or not os.path.isdir(font_dir):
            log.error(f"Font directory not found or invalid: '{font_dir}'")
            return False

        font_name = self.subtitle_config.get('font_name')
        if not font_name:
            log.warning("`font_name` is not specified in subtitle config.")
        
        return True
