# -*- coding: utf-8 -*-
import subprocess
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SubtitleGeneratorFFFFF:
    def __init__(self, language="eng"):
        """
        初始化 SubtitleGenerator。
        :param language: aeneas 使用的语言, 例如 'eng' 表示英语, 'chi' 表示中文。
        """
        self.language = language

    def generate(self, audio_path: str, text_path: str, output_path: str):
        """
        使用 aeneas 生成字幕文件。
        :param audio_path: 音频文件路径。
        :param text_path: 纯文本文件路径 (UTF-8 编码)。
        :param output_path: 字幕输出文件路径 (例如 .srt)。
        """
        audio_file = Path(audio_path)
        text_file = Path(text_path)
        output_file = Path(output_path)

        if not audio_file.exists():
            logging.error(f"音频文件未找到: {audio_path}")
            raise FileNotFoundError(f"音频文件未找到: {audio_path}")

        if not text_file.exists():
            logging.error(f"文本文件未找到: {text_path}")
            raise FileNotFoundError(f"文本文件未找到: {text_path}")

        # 确保输出目录存在
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # aeneas 命令参数
        # 更多信息请参考: https://www.readbeyond.it/aeneas/docs/clitools.html
        # 恢复到纯文本输入，并设置更激进的语音检测级别
        config_string = f"task_language={self.language}|is_text_type=plain|os_task_file_format=srt|task_speech_detector_level=2"

        command = [
            "python",
            "-m",
            "aeneas.tools.execute_task",
            str(audio_file.resolve()),
            str(text_file.resolve()),
            config_string,
            str(output_file.resolve())
        ]

        try:
            logging.info(f"执行 aeneas 命令: {' '.join(command)}")
            result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
            logging.info("aeneas 命令执行成功。")
            logging.info(f"字幕文件已生成: {output_path}")
            if result.stdout:
                logging.debug(f"STDOUT: {result.stdout}")
            if result.stderr:
                logging.warning(f"STDERR: {result.stderr}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"aeneas 命令执行失败。返回码: {e.returncode}")
            logging.error(f"STDOUT: {e.stdout}")
            logging.error(f"STDERR: {e.stderr}")
            raise RuntimeError(f"Aeneas execution failed. See logs for details.") from e
        except FileNotFoundError:
            logging.error("错误: 'python' 命令未找到。请确保 Python 已经安装并且在系统的 PATH 中。")
            raise