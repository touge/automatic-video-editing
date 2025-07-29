import sys # 导入 sys
import subprocess
import os
from pathlib import Path
from tqdm import tqdm
import re
import torch
from faster_whisper import WhisperModel # 确保 Faster Whisper 已安装

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

    def _extract_video_id(self, url: str) -> str:
        # 简化视频 ID 提取，针对 YouTube URL
        match = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})(?:&|\?)?.*', url)
        if match:
            return match.group(1)
        return "unknown_video" # 无法提取 ID 时的备用

    def download_audio(self, output_dir: str):
        """
        下载视频音频。
        优化：检查音频文件是否已存在，如果存在则跳过下载。
        """
        print("🎵 Downloading audio...")
        os.makedirs(output_dir, exist_ok=True)
        
        # 构建可能的音频文件路径，使用 %(title)s 和 %(ext)s
        # yt-dlp 可能会下载为 .webm, .m4a, .opus, .mp3 等
        # 我们需要先尝试查找已存在的音频文件
        
        # 查找已存在的音频文件
        existing_audio_files = []
        for f_name in os.listdir(output_dir):
            # 查找文件名包含 video_id 且是常见音频格式的文件
            if self.video_id in f_name and (f_name.endswith(".m4a") or f_name.endswith(".webm") or f_name.endswith(".opus") or f_name.endswith(".mp3")):
                existing_audio_files.append(os.path.join(output_dir, f_name))
        
        if existing_audio_files:
            self.audio_path = existing_audio_files[0] # 取第一个找到的
            print(f"✅ Audio file already exists: {self.audio_path}. Skipping download.")
            return

        # 如果音频文件不存在，则执行下载
        audio_output_path = os.path.join(output_dir, f"%(title)s[{self.video_id}].%(ext)s")
        command = [
            sys.executable, "-m", "yt_dlp", "-x", "-f", "bestaudio", self.url,
            "-o", audio_output_path
        ] + self._proxy_arg()
        
        try:
            print("尝试下载音频，使用 python -m yt_dlp -x -f bestaudio 模式...")
            subprocess.run(command, check=True) # 移除 shell=True，因为现在直接调用 python
            
            # 下载完成后，再次查找实际下载的音频文件路径
            # 因为 yt-dlp 会根据 %(title)s 生成具体文件名
            newly_downloaded_audio_files = []
            for f_name in os.listdir(output_dir):
                if self.video_id in f_name and (f_name.endswith(".m4a") or f_name.endswith(".webm") or f_name.endswith(".opus") or f_name.endswith(".mp3")):
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
