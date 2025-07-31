import sys
import subprocess
import os
from pathlib import Path
from typing import Optional
from tqdm import tqdm
import re
import torch
from faster_whisper import WhisperModel
import yt_dlp
import fnmatch
import json

class SubtitlesProcessor:
    def __init__(self, url: str, proxy: str = None):
        self.url = url
        self.proxy = proxy
        self.video_id = self._extract_video_id(url)
        self.audio_path = None
        # self.nltk_data_path 和相关方法已移除
        # jieba 导入已移除，因为不再进行复杂分句

    def _proxy_arg(self) -> list[str]:
        return ["--proxy", self.proxy] if self.proxy else []

    def download_platform_subtitles(self, output_dir: str, target_filename_base: str) -> Optional[str]:
        """
        尝试从视频平台下载字幕，按照优先级：简体中文、繁体中文、英文。
        优先下载 SRT 格式，如果只有 VTT 则下载 VTT 并转换为 SRT。
        """
        print("🌍 尝试从视频平台下载字幕...")
        
        preferred_langs = ['zh-Hans', 'zh-Hant', 'en']
        target_format = 'srt'
        fallback_format = 'vtt'

        os.makedirs(output_dir, exist_ok=True)

        try:
            ydl_info_opts = {
                'skip_download': True,
                'quiet': True,
                'proxy': self.proxy if self.proxy else None,
            }
            with yt_dlp.YoutubeDL(ydl_info_opts) as ydl_info:
                info_dict = ydl_info.extract_info(self.url, download=False)

            available_subtitles = info_dict.get('subtitles', {})

            if not available_subtitles:
                print("  - 平台没有可用字幕。")
                return None

            sub_lang_to_download = None
            needs_conversion = False

            for lang in preferred_langs:
                if lang in available_subtitles:
                    sub_lang_to_download = lang
                    if not any(s['ext'] == target_format for s in available_subtitles[lang]):
                        if any(s['ext'] == fallback_format for s in available_subtitles[lang]):
                            needs_conversion = True
                    break
            
            if not sub_lang_to_download:
                print(f"  - 未能找到符合优先级的字幕 ({preferred_langs})。")
                return None

            sub_format_to_request = fallback_format if needs_conversion else target_format
            
            yt_dlp_command = [
                sys.executable, "-m", "yt_dlp",
                "--skip-download", "--write-subs",
                "--sub-langs", sub_lang_to_download,
                "--sub-format", sub_format_to_request,
                "-o", os.path.join(output_dir, f"{self.video_id}.%(ext)s"),
                self.url
            ]
            if self.proxy:
                yt_dlp_command.extend(["--proxy", self.proxy])

            subprocess.run(yt_dlp_command, check=True, capture_output=True, text=True, errors='replace')
            
            found_subtitle_path = None
            
            # 查找下载的文件
            downloaded_sub_ext = fallback_format if needs_conversion else target_format
            search_pattern = f"{self.video_id}*.{sub_lang_to_download}.{downloaded_sub_ext}"
            
            for filename in fnmatch.filter(os.listdir(output_dir), search_pattern):
                found_path = Path(os.path.join(output_dir, filename))
                if found_path.exists() and found_path.stat().st_size > 0:
                    if needs_conversion:
                        srt_path = found_path.with_suffix('.srt')
                        try:
                            self._convert_vtt_to_srt(str(found_path), str(srt_path))
                            found_subtitle_path = srt_path
                        except Exception as e:
                            print(f"  ❌ VTT转换SRT失败: {e}")
                            continue
                    else:
                        found_subtitle_path = found_path
                    break

            if found_subtitle_path:
                final_srt_path = Path(output_dir) / f"{target_filename_base}.srt"
                if found_subtitle_path.resolve() != final_srt_path.resolve():
                     # 如果目标文件已存在，先删除
                    if os.path.exists(final_srt_path):
                        os.remove(final_srt_path)
                    os.rename(found_subtitle_path, final_srt_path)
                print(f"  ✅ 成功下载并保存字幕: {final_srt_path}")
                return str(final_srt_path)
            else:
                print(f"  ⚠️ yt-dlp 报告成功，但未能找到匹配的字幕文件。")
                return None

        except subprocess.CalledProcessError as e:
            print(f"❌ yt-dlp 命令行执行失败: {e.stderr}")
        except yt_dlp.utils.DownloadError as e:
            print(f"❌ yt-dlp 在获取信息时发生错误: {e}")
        except Exception as e:
            print(f"❌ 下载平台字幕时发生未知错误: {e}")
        
        return None

    def _convert_vtt_to_srt(self, vtt_path: str, srt_path: str):
        """
        使用 ffmpeg 将 VTT 字幕文件转换为 SRT 格式。
        """
        try:
            ffmpeg_command = ['ffmpeg', '-y', '-i', vtt_path, srt_path]
            subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True)
            print(f"  ✅ VTT手动转换为SRT成功: {srt_path}")
            os.remove(vtt_path)
        except subprocess.CalledProcessError as e:
            print(f"  ❌ FFmpeg手动转换VTT失败。stdout: {e.stdout}, stderr: {e.stderr}")
            raise
        except Exception as e:
            print(f"  ❌ 手动转换VTT时发生未知错误: {e}")
            raise

    def _extract_video_id(self, url: str) -> str:
        # 简化视频 ID 提取，针对 YouTube URL
        match = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})(?:&|\?)?.*', url)
        if match:
            return match.group(1)
        return "unknown_video" # 无法提取 ID 时的备用

    def download_audio(self, output_dir: str, filename_base: str):
        """
        下载视频音频。
        """
        print("🎵 Downloading audio...")
        os.makedirs(output_dir, exist_ok=True)
        
        # 检查音频文件是否已存在
        # 注意：这里我们假设一个任务只处理一个音频，所以不严格检查后缀
        for f_name in os.listdir(output_dir):
            if f_name.startswith(filename_base) and any(f_name.endswith(ext) for ext in ['.m4a', '.webm', '.opus', '.mp3']):
                self.audio_path = os.path.join(output_dir, f_name)
                print(f"✅ Audio file already exists: {self.audio_path}. Skipping download.")
                return

        # 如果音频文件不存在，则执行下载
        audio_output_path = os.path.join(output_dir, f"{filename_base}.%(ext)s")
        command = [
            sys.executable, "-m", "yt_dlp",
            "-x", "-f", "bestaudio", self.url,
            "-o", audio_output_path
        ]
        if self.proxy:
            command.extend(["--proxy", self.proxy])
        
        try:
            print("尝试下载音频，使用 yt-dlp -x -f bestaudio 模式...")
            subprocess.run(command, check=True)
            
            # 下载完成后，再次查找实际下载的音频文件路径
            newly_downloaded_audio_files = []
            for f_name in os.listdir(output_dir):
                if f_name.startswith(filename_base) and any(f_name.endswith(ext) for ext in ['.m4a', '.webm', '.opus', '.mp3']):
                    newly_downloaded_audio_files.append(os.path.join(output_dir, f_name))
            
            if newly_downloaded_audio_files:
                self.audio_path = newly_downloaded_audio_files[0]
                print(f"✅ Audio downloaded to: {self.audio_path}")
            else:
                print(f"⚠️ 无法在 '{output_dir}' 目录中找到下载的音频文件，但 yt-dlp 命令成功完成。")
                self.audio_path = None

        except subprocess.CalledProcessError as e:
            print(f"❌ 下载音频失败: {e.stderr}")
            self.audio_path = None
        except Exception as e:
            print(f"❌ 发生未知错误：{e}")
            self.audio_path = None

    def Otranscribe_with_whisper(self, model_dir: str):
        if not self.audio_path or not Path(self.audio_path).exists():
            print("❌ Audio file not found for transcription.")
            return []

        print(f"🎙️ Transcribing audio with Faster Whisper model: {model_dir}...")
        try:
            # 确保 torch 已导入且可用，如果可用则使用 cuda
            model = WhisperModel(model_dir, device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16")
            segments, info = model.transcribe(self.audio_path, beam_size=5)
            print(f"✅ Detected language: {info.language} with probability {info.language_probability:.4f}")
            
            segments_list = list(segments) # 转换为列表以便多次访问
            # print(f"DEBUG: Transcribed segments count: {len(segments_list)}") # 调试打印已移除
            
            return segments_list
        except ImportError:
            print("❌ PyTorch not found. Please install PyTorch for GPU support or ensure it's in your environment.")
            print("Falling back to CPU if possible, or try installing torch: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 (for CUDA 11.8)")
            try:
                model = WhisperModel(model_dir, device="cpu", compute_type="int8") # CPU 模式可以使用 int8 优化
                segments, info = model.transcribe(self.audio_path, beam_size=5)
                print(f"✅ Detected language: {info.language} with probability {info.language_probability:.4f}")
                
                segments_list = list(segments)
                # print(f"DEBUG: Transcribed segments count (CPU fallback): {len(segments_list)}") # 调试打印已移除
                
                return segments_list
            except Exception as e:
                print(f"❌ Error during CPU transcription fallback: {e}")
                return []
        except Exception as e:
            print(f"❌ Error during transcription: {e}")
            return []


    def OOtranscribe_with_whisper(self, model_dir: str):
        if not self.audio_path or not Path(self.audio_path).exists():
            print("❌ Audio file not found for transcription.")
            return []

        print(f"🎙️ Transcribing audio with Faster Whisper model: {model_dir}...")
        try:
            model = WhisperModel(model_dir, device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16")
            
            # 使用 tqdm 来显示进度条
            # Faster Whisper 的 transcribe 方法返回一个迭代器
            # info 对象包含 duration_ms，可以用来估算总进度
            # 也可以直接迭代 segments，tqdm 会自动计算迭代次数
            
            # 第一次调用 transcribe 时获取 segments 和 info
            segments_generator, info = model.transcribe(self.audio_path, beam_size=5)
            print(f"✅ Detected language: {info.language} with probability {info.language_probability:.4f}")
            
            segments_list = []
            # 获取音频总时长（毫秒），用于进度条
            total_audio_duration_ms = info.duration * 1000 
            
            # 使用 tqdm 包装 segments 迭代器，并根据音频时长显示进度
            # desc: 进度条描述
            # total: 迭代的总量，这里用音频总时长
            # unit: 单位
            # unit_scale: 单位的缩放比例 (ms -> s)
            # bar_format: 自定义进度条格式，显示已转录时长
            
            # 记录起始时间，用于计算已转录时长
            start_time_segment = 0.0

            # 收集 segments 并在 tqdm 中显示进度
            for segment in tqdm(segments_generator, 
                                desc="🔊 Transcribing Audio", 
                                unit="s", unit_scale=True,
                                total=total_audio_duration_ms / 1000, # total in seconds
                                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]"):
                
                segments_list.append(segment)
                # 更新进度条的当前值，使用当前 segment 的结束时间
                tqdm.write_text(tqdm._instances[0], f"Processed: {self._format_timestamp(segment.end)}", end='\r') # 显示当前转录到哪个时间点
                
            return segments_list
            
        except ImportError:
            print("❌ PyTorch not found. Please install PyTorch for GPU support or ensure it's in your environment.")
            print("Falling back to CPU if possible, or try installing torch: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 (for CUDA 11.8)")
            try:
                model = WhisperModel(model_dir, device="cpu", compute_type="int8")
                
                segments_generator, info = model.transcribe(self.audio_path, beam_size=5)
                print(f"✅ Detected language: {info.language} with probability {info.language_probability:.4f}")
                
                segments_list = []
                total_audio_duration_ms = info.duration * 1000
                
                for segment in tqdm(segments_generator, 
                                    desc="🔊 Transcribing Audio (CPU)", 
                                    unit="s", unit_scale=True,
                                    total=total_audio_duration_ms / 1000,
                                    bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]"):
                    segments_list.append(segment)
                    tqdm.write_text(tqdm._instances[0], f"Processed: {self._format_timestamp(segment.end)}", end='\r')
                    
                return segments_list
            except Exception as e:
                print(f"❌ Error during CPU transcription fallback: {e}")
                return []
        except Exception as e:
            print(f"❌ Error during transcription: {e}")
            return []


    def transcribe_with_whisper(self, model_dir: str):
        if not self.audio_path or not Path(self.audio_path).exists():
            print("❌ Audio file not found for transcription.")
            return []

        print(f"🎙️ Transcribing audio with Faster Whisper model: {model_dir}...")
        try:
            model = WhisperModel(model_dir, device="cuda" if torch.cuda.is_available() else "cpu", compute_type="float16")
            
            segments_generator, info = model.transcribe(self.audio_path, beam_size=5)
            print(f"✅ Detected language: {info.language} with probability {info.language_probability:.4f}")
            
            segments_list = []
            
            # 简化进度显示，只打印已处理的时间
            total_duration_seconds = info.duration # 获取音频总时长（秒）

            print("🔊 Transcription Progress:")
            
            # 使用 tqdm 作为简单的迭代器包装，不再依赖其复杂的 bar_format 和 write_text
            # 仅通过迭代 segment 来更新进度
            for i, segment in enumerate(segments_generator):
                segments_list.append(segment)
                
                # 计算已处理的百分比和时间
                progress_percentage = (segment.end / total_duration_seconds) * 100 if total_duration_seconds > 0 else 0
                
                # 打印已转录的时长，使用 \r 回到行首，实现动态更新
                # flush=True 确保立即打印
                print(f"  Processed: {self._format_timestamp(segment.end)} / {self._format_timestamp(total_duration_seconds)} ({progress_percentage:.1f}%)", end='\r', flush=True)
            
            # 转录完成后，打印一个空行或完成信息，清除上一行的 \r 效果
            print("\n✅ Transcription Complete!")
            
            return segments_list
            
        except ImportError:
            print("❌ PyTorch not found. Please install PyTorch for GPU support or ensure it's in your environment.")
            print("Falling back to CPU if possible, or try installing torch: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 (for CUDA 11.8)")
            try:
                model = WhisperModel(model_dir, device="cpu", compute_type="int8")
                
                segments_generator, info = model.transcribe(self.audio_path, beam_size=5)
                print(f"✅ Detected language: {info.language} with probability {info.language_probability:.4f}")
                
                segments_list = []
                total_duration_seconds = info.duration

                print("🔊 Transcription Progress (CPU Fallback):")
                for i, segment in enumerate(segments_generator):
                    segments_list.append(segment)
                    
                    progress_percentage = (segment.end / total_duration_seconds) * 100 if total_duration_seconds > 0 else 0
                    print(f"  Processed: {self._format_timestamp(segment.end)} / {self._format_timestamp(total_duration_seconds)} ({progress_percentage:.1f}%)", end='\r', flush=True)
                
                print("\n✅ Transcription Complete (CPU Fallback)!")
                
                return segments_list
            except Exception as e:
                print(f"❌ Error during CPU transcription fallback: {e}")
                return []
        except Exception as e:
            print(f"❌ Error during transcription: {e}")
            return []

    def export_srt(self, segments: list, output_dir: str, filename: str) -> str:
        """
        导出为 SRT 字幕文件。此方法保留，您可以选择使用或不使用。
        """
        print("📤 Exporting subtitles to SRT file...")
        srt_path = os.path.join(output_dir, f"{filename}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, segment in enumerate(tqdm(segments, desc="📄 Exporting SRT")):
                start_time = self._format_timestamp(segment.start)
                end_time = self._format_timestamp(segment.end)
                f.write(f"{i + 1}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{segment.text.strip()}\n\n")
        print(f"✅ SRT exported to: {srt_path}")
        return srt_path

    def _format_timestamp(self, seconds: float) -> str:
        milliseconds = int((seconds * 1000) % 1000)
        seconds_int = int(seconds)
        minutes = seconds_int // 60
        hours = minutes // 60
        return f"{hours:02}:{minutes % 60:02}:{seconds_int % 60:02},{milliseconds:03}"

    def export_line_txt(self, srt_file_path: str, output_dir: str):
        """
        将 SRT 文件转换为纯文本文件，每行一个字幕条目，去除时间轴和序号。
        """
        print(f"📖 Starting to process SRT file for raw text export: {srt_file_path}")

        manuscript_lines = []
        try:
            with open(srt_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # 确保只提取实际的文本行，跳过数字和时间戳行
                    if not line.isdigit() and "-->" not in line and line:
                        manuscript_lines.append(line)
        except FileNotFoundError:
            print(f"❌ Error: SRT file not found at {srt_file_path}")
            return
        except Exception as e:
            print(f"❌ Error reading SRT file {srt_file_path}: {e}")
            return

        if not manuscript_lines:
            print("⚠️ No text extracted from SRT file. Aborting raw text export.")
            return
        
        print("⚙️ 将 SRT 转换为纯文本文件，去除时间轴并按行输出...")
        original_filename_base = Path(srt_file_path).stem
        manuscript_path = os.path.join(output_dir, f"{original_filename_base}_line.txt") # 命名为 _line.txt
        
        print(f"📝 Saving line-by-line text to: {manuscript_path}")
        with open(manuscript_path, "w", encoding="utf-8") as f:
            for line in manuscript_lines:
                f.write(line + "\n") # 每行一个 SRT 条目的文本
        print("✅ Line-by-line text saved.")
