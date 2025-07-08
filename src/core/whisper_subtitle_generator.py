# -*- coding: utf-8 -*-
import whisper
import logging
import re
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def format_timestamp(seconds: float) -> str:
    """将秒转换为 SRT 时间戳格式 (HH:MM:SS,ms)"""
    assert seconds >= 0, "non-negative timestamp expected"
    milliseconds = round(seconds * 1000.0)
    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000
    minutes = milliseconds // 60_000
    milliseconds %= 60_000
    seconds = milliseconds // 1_000
    milliseconds %= 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

class WhisperSubtitleGenerator:
    def __init__(self, model_name="base", models_dir="models"):
        """
        初始化 WhisperSubtitleGenerator。
        :param model_name: 要使用的 Whisper 模型名称 (例如 "tiny", "base", "small", "medium", "large")。
        :param models_dir: 存放模型文件的目录。
        """
        model_path = Path(models_dir) / f"{model_name}.pt"
        model_path.parent.mkdir(parents=True, exist_ok=True)
        logging.info(f"正在加载 Whisper 模型: {model_name}")
        self.model = whisper.load_model(str(model_path) if model_path.exists() else model_name, download_root=models_dir)
        logging.info("Whisper 模型加载完成。")

    def generate(self, audio_path: str, output_path: str, language: str = "zh", min_line_length: int = 8, max_line_length: int = 15):
        """
        使用 Whisper 生成字幕文件，并基于词级别时间戳进行智能合并与分割。
        """
        audio_file = Path(audio_path)
        output_file = Path(output_path)
        if not audio_file.exists():
            logging.error(f"音频文件未找到: {audio_path}")
            raise FileNotFoundError(f"音频文件未找到: {audio_path}")
        output_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            logging.info(f"开始使用 Whisper 转录音频 (语言: {language})...")
            result = self.model.transcribe(audio_path, verbose=True, language=language, word_timestamps=True)
            
            words = result.get("words", [])
            if not words:
                logging.error("无法获取词级别时间戳，无法生成优化字幕。")
                return False

            # --- 1. 严格按最大长度切分 ---
            preliminary_subs = []
            line_buffer = []
            for word_info in words:
                current_text = "".join(w['word'] for w in line_buffer)
                if len(current_text) + len(word_info['word']) > max_line_length:
                    if line_buffer:
                        preliminary_subs.append(line_buffer)
                    line_buffer = [word_info]
                else:
                    line_buffer.append(word_info)
            if line_buffer:
                preliminary_subs.append(line_buffer)

            # --- 2. 合并过短的行 ---
            final_subs = []
            i = 0
            while i < len(preliminary_subs):
                current_line = preliminary_subs[i]
                current_text = "".join(w['word'] for w in current_line)
                
                if len(current_text) < min_line_length and (i + 1) < len(preliminary_subs):
                    next_line = preliminary_subs[i+1]
                    merged_line = current_line + next_line
                    if len("".join(w['word'] for w in merged_line)) <= max_line_length:
                        final_subs.append(merged_line)
                        i += 2
                        continue
                
                final_subs.append(current_line)
                i += 1

            # --- 3. 写入文件并清理标点 ---
            with open(output_file, "w", encoding="utf-8") as srt_file:
                unwanted_punctuation_pattern = r"[？，。；?!,;]"
                srt_counter = 1
                for sub_words in final_subs:
                    if not sub_words: continue
                    start_time = format_timestamp(sub_words[0]['start'])
                    end_time = format_timestamp(sub_words[-1]['end'])
                    text = "".join(w['word'] for w in sub_words).strip()
                    final_text = re.sub(unwanted_punctuation_pattern, '', text)
                    
                    if not final_text: continue
                    srt_file.write(f"{srt_counter}\n")
                    srt_file.write(f"{start_time} --> {end_time}\n")
                    srt_file.write(f"{final_text}\n\n")
                    srt_counter += 1

            logging.info(f"字幕文件已成功生成: {output_path}")
            return True

        except Exception as e:
            logging.error(f"使用 Whisper 生成字幕时发生错误: {e}")
            raise RuntimeError(f"Whisper transcription failed: {e}") from e
