import json
import subprocess
from tqdm import tqdm
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from time import sleep


class SegmentedVideoComposer:
    def __init__(
        self,
        video_struct_path,
        input_audio_path,
        output_video_path,
        temp_dir="temp_segments",
        resolution=(1920, 1080),
        trim_audio=True,
        silent=True,
        strict_mode=True,
        max_workers=8
    ):
        """
        ✅ 初始化配置参数
        :param video_struct_path: 视频结构 JSON 文件路径（含片段和素材列表）
        :param input_audio_path: 合并用音频文件路径
        :param output_video_path: 最终输出视频路径
        :param temp_dir: 存储中间段落视频的目录
        :param resolution: 输出视频分辨率，默认 1920x1080
        :param trim_audio: 是否根据总视频时长裁剪音频
        :param silent: 是否静默运行 FFmpeg（不打印过程）
        :param strict_mode: 若任一段落失败则终止流程
        :param max_workers: 获取素材时长的线程数
        """
        self.video_struct_path = Path(video_struct_path)
        self.input_audio_path = input_audio_path
        self.output_video_path = output_video_path
        self.temp_dir = Path(temp_dir)
        self.width, self.height = resolution
        self.trim_audio = trim_audio
        self.silent = silent
        self.strict_mode = strict_mode
        self.max_workers = max_workers
        self.structure = []

    def load_structure(self):
        """📦 加载 JSON 视频结构信息"""
        with open(self.video_struct_path, "r", encoding="utf-8") as f:
            self.structure = json.load(f)

    def get_duration(self, path):
        """⏱️ 获取素材的真实时长（使用 ffprobe）"""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ]
        try:
            output = subprocess.check_output(cmd).decode().strip()
            return round(float(output), 2)
        except Exception:
            return 0.0

    def process_segment(self, segment, seg_index):
        """🎬 处理一个段落，按比例裁剪并生成段落视频"""
        scenes = segment["scenes"]
        target_duration = round(segment["duration"], 2)
        asset_paths = [scene["asset_path"] for scene in scenes]

        # ✅ 多线程获取素材真实时长
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            real_durations = list(tqdm(executor.map(self.get_duration, asset_paths),
                                       total=len(scenes),
                                       desc=f"⏱️ 获取素材 Segment{seg_index:02d}"))

        total_real = sum(real_durations)
        for scene, real in zip(scenes, real_durations):
            scene["real_duration"] = real
            ratio = real / total_real if total_real > 0 else 0
            scene["allocated_duration"] = round(ratio * target_duration, 2)

        input_args, filter_lines, concat_labels = [], [], []
        # print(f"\n🧩 Segment {seg_index:02d} 分配详情（目标 {target_duration}s）：")
        for idx, scene in enumerate(scenes):
            input_args += ["-i", scene["asset_path"]]
            dur = scene["allocated_duration"]
            v_label = f"v{idx}"
            # ✅ 统一尺寸 + 补黑边 + 强制比例
            filter_lines.append(
                f"[{idx}:v]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1,trim=0:{dur},setpts=PTS-STARTPTS[{v_label}];"
            )
            concat_labels.append(f"[{v_label}]")
            print(f"  🎞️ {scene['asset_path']} → 分配 {dur} 秒")

        filter_complex = "".join(filter_lines)
        filter_complex += f"{''.join(concat_labels)}concat=n={len(scenes)}:v=1:a=0[outv]"

        output_path = self.temp_dir / f"segment_{seg_index:02d}.mp4"
        ffmpeg_cmd = ["ffmpeg"] + input_args + [
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264",
            "-crf", "23",
            "-preset", "ultrafast",
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

        return output_path

    def combine_segments(self, segment_paths):
        """📽️ 合并所有段落为主视频，并加入音频"""
        valid_segments = [p for p in segment_paths if p and p.exists() and p.stat().st_size > 1024]
        if not valid_segments:
            raise RuntimeError("❌ 无可用段落可合并")

        input_args, concat_labels = [], []
        for idx, path in enumerate(valid_segments):
            input_args += ["-i", str(path)]
            concat_labels.append(f"[{idx}:v]")

        filter_complex = "".join(concat_labels)
        filter_complex += f"concat=n={len(valid_segments)}:v=1:a=0[outv]"

        total_duration = sum(seg["duration"] for seg in self.structure)
        if self.trim_audio:
            audio_input = ["-ss", "0", "-t", str(total_duration), "-i", self.input_audio_path]
            audio_index = len(valid_segments)
        else:
            audio_input = ["-i", self.input_audio_path]
            audio_index = len(valid_segments)

        ffmpeg_cmd = ["ffmpeg"] + input_args + audio_input + [
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", f"{audio_index}:a",
            "-c:v", "libx264",
            "-crf", "23",
            "-preset", "ultrafast",
            "-threads", "4",
            "-shortest",
            "-y", self.output_video_path
        ]

        # ✅ 模拟合并阶段进度条
        print("\n🔗 合并所有段落为完整视频 ...")
        for _ in tqdm(range(100), desc="🧪 合并中", ncols=80):
            sleep(0.01)

        subprocess.run(
            ffmpeg_cmd,
            stdout=subprocess.DEVNULL if self.silent else None,
            stderr=subprocess.DEVNULL if self.silent else None
        )

    def execute(self):
        """🏁 执行完整流程：载入 → 分段处理 → 合并输出"""
        self.load_structure()
        self.temp_dir.mkdir(exist_ok=True)

        segment_outputs = []
        print(f"\n🎞️ 共 {len(self.structure)} 个视频段落待处理")
        for i, segment in enumerate(self.structure):
            print(f"\n🎬 正在处理 Segment {i+1}/{len(self.structure)}")
            output = self.process_segment(segment, i)
            segment_outputs.append(output)

        self.combine_segments(segment_outputs)
        print(f"\n✅ 成片完成：{self.output_video_path}")
