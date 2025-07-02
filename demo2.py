#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import subprocess
import sys
import shutil
import tempfile
import time
import argparse
from pathlib import Path

import yaml
from tqdm import tqdm

def load_config(path: Path):
    defaults = {
        'width': 1920,
        'height': 1080,
        'fps': 30,
        'encoder': 'libx264',
        'max_clip_duration': 8.0,
        'min_clip_duration': 3.0
    }
    if not path.exists():
        return defaults
    cfg = yaml.safe_load(path.read_text(encoding='utf-8')).get('video', {})
    return {**defaults, **cfg}

def detect_video_encoder():
    try:
        encs = subprocess.run(
            ['ffmpeg', '-hide_banner', '-encoders'],
            capture_output=True, text=True, check=True
        ).stdout.lower()
    except:
        return 'libx264', ['-preset', 'veryfast'], False

    if 'h264_nvenc' in encs:
        return 'h264_nvenc', ['-preset', 'p2'], False
    if 'h264_qsv' in encs:
        return 'h264_qsv', [], True
    if 'h264_videotoolbox' in encs:
        return 'h264_videotoolbox', [], False
    return 'libx264', ['-preset', 'veryfast'], False

def run_cmd(cmd, debug):
    if debug:
        subprocess.run(cmd, check=True)
    else:
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)

def trim_segment(src, dur, dst, video_cfg, codec, extra, hwaccel, debug):
    vf = (
        f"scale={video_cfg['width']}:-2:"
        "force_original_aspect_ratio=decrease,"
        f"pad={video_cfg['width']}:{video_cfg['height']}:"
        "(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={video_cfg['fps']}"
    )
    cmd = ['ffmpeg', '-y']
    if hwaccel and 'qsv' in codec:
        cmd += ['-hwaccel', 'qsv']
    cmd += [
        '-ss', '0',
        '-t', str(dur),
        '-i', str(src),
        '-vf', vf,
        '-c:v', codec, *extra,
        '-c:a', 'aac',
        str(dst)
    ]
    run_cmd(cmd, debug)

def make_concat_list(segments, list_path):
    with list_path.open('w', encoding='utf-8') as f:
        for seg in segments:
            f.write(f"file '{seg.as_posix()}'\n")

def concat_with_progress(
    list_txt: Path,
    out_mp4: Path,
    video_cfg: dict,
    codec: str,
    extra: list,
    srt: Path|None,
    hwaccel: bool,
    total_duration: float,
    debug: bool
):
    base = [
        'ffmpeg', '-y',
        '-fflags', '+genpts',
        '-f', 'concat', '-safe', '0',
        '-i', str(list_txt),
        '-avoid_negative_ts', 'make_zero',
    ]
    if srt and srt.exists():
        base += ['-vf', f"subtitles={srt.as_posix()}"]
    if hwaccel and 'qsv' in codec:
        base += ['-hwaccel', 'qsv']
    base += ['-c:v', codec, *extra, '-c:a', 'aac', str(out_mp4)]

    if debug:
        subprocess.run(base, check=True)
        return

    progress_file = list_txt.parent / 'progress_video.log'
    cmd = base.copy()
    cmd.insert(1, str(progress_file))
    cmd.insert(1, '-progress')

    proc = subprocess.Popen(cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    pbar = tqdm(total=round(total_duration, 2),
                unit='s', desc='拼接视频')
    last_t = 0.0
    try:
        while proc.poll() is None:
            time.sleep(0.2)
            if not progress_file.exists():
                continue
            for line in progress_file.read_text().splitlines():
                if line.startswith('out_time_us='):
                    val = line.split('=', 1)[1]
                    try:
                        cur = int(val) / 1_000_000
                    except ValueError:
                        continue
                    if cur > last_t:
                        pbar.update(cur - last_t)
                        last_t = cur
            pbar.refresh()
        if last_t < total_duration:
            pbar.update(total_duration - last_t)
    finally:
        pbar.close()
        if progress_file.exists():
            progress_file.unlink()
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg 拼接失败")

def merge_audio_with_progress(
    video_mp4: Path,
    audio_file: Path,
    final_mp4: Path,
    total_duration: float,
    debug: bool
):
    base = [
        'ffmpeg', '-y',
        '-i', str(video_mp4),
        '-i', str(audio_file),
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-map', '0:v:0',
        '-map', '1:a:0',
        '-shortest',
        str(final_mp4)
    ]

    if debug:
        subprocess.run(base, check=True)
        return

    progress_file = video_mp4.parent / 'progress_audio.log'
    cmd = base.copy()
    cmd.insert(1, str(progress_file))
    cmd.insert(1, '-progress')

    proc = subprocess.Popen(cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    pbar = tqdm(total=round(total_duration, 2),
                unit='s', desc='合并音频')
    last_t = 0.0
    try:
        while proc.poll() is None:
            time.sleep(0.2)
            if not progress_file.exists():
                continue
            for line in progress_file.read_text().splitlines():
                if line.startswith('out_time_us='):
                    val = line.split('=', 1)[1]
                    try:
                        cur = int(val) / 1_000_000
                    except ValueError:
                        continue
                    if cur > last_t:
                        pbar.update(cur - last_t)
                        last_t = cur
            pbar.refresh()
        if last_t < total_duration:
            pbar.update(total_duration - last_t)
    finally:
        pbar.close()
        if progress_file.exists():
            progress_file.unlink()
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg 合并音频失败")

def main():
    p = argparse.ArgumentParser(
        description="按 duration_parts 裁剪+拼接所有场景，支持外挂 SRT & 合并音频，带进度条/调试模式"
    )
    p.add_argument('-c', '--config', default='config.yaml',
                   help="YAML 配置文件，包含 video 参数")
    p.add_argument('-j', '--scenes', default='scenes.json',
                   help="场景 JSON 文件")
    p.add_argument('-s', '--srt', help="外挂 SRT 字幕文件（可选）")
    p.add_argument('-a', '--audio', help="外挂音频文件（可选）")
    p.add_argument('-o', '--output', default='output.mp4',
                   help="最终输出视频文件")
    p.add_argument('--debug', action='store_true',
                   help="调试模式：打印 FFmpeg 日志，禁用进度条")
    args = p.parse_args()

    video_cfg = load_config(Path(args.config))

    scenes_file = Path(args.scenes)
    if not scenes_file.exists():
        sys.exit(f"错误：找不到 {scenes_file}")
    data = json.loads(scenes_file.read_text(encoding='utf-8'))
    if not data:
        sys.exit("错误：场景数据为空")

    assets_all, durations_all = [], []
    for idx, sc in enumerate(data):
        aps = sc.get('asset_paths', [])
        dps = sc.get('duration_parts', [])
        if len(aps) != len(dps):
            print(f"警告：第{idx+1}场景 asset_paths 与 duration_parts 数量不匹配，已跳过",
                  file=sys.stderr)
            continue
        assets_all += [Path(p) for p in aps]
        durations_all += dps

    if not assets_all:
        sys.exit("错误：没有可用素材来裁剪")

    total_duration = sum(durations_all)
    codec, extra_args, hwaccel = detect_video_encoder()
    if args.debug:
        print(f"[DEBUG] video_cfg={video_cfg}")
        print(f"[DEBUG] codec={codec}, hwaccel={hwaccel}, extra={extra_args}")

    tmpdir = Path(tempfile.mkdtemp(prefix='vid_all_'))
    segs = []
    try:
        if args.debug:
            for i, (src, dur) in enumerate(zip(assets_all, durations_all)):
                dst = tmpdir / f"seg_{i:04d}.mp4"
                print(f"[DEBUG] 裁剪第{i}段: {src} → {dur}s")
                trim_segment(src, dur, dst,
                             video_cfg, codec, extra_args, hwaccel, True)
                segs.append(dst)
        else:
            with tqdm(total=len(assets_all), desc="裁剪片段", unit="段") as pbar:
                for i, (src, dur) in enumerate(zip(assets_all, durations_all)):
                    dst = tmpdir / f"seg_{i:04d}.mp4"
                    trim_segment(src, dur, dst,
                                 video_cfg, codec, extra_args, hwaccel, False)
                    segs.append(dst)
                    pbar.update(1)

        list_txt = tmpdir / "list.txt"
        make_concat_list(segs, list_txt)
        video_only = tmpdir / "video_only.mp4"
        concat_with_progress(
            list_txt, video_only,
            video_cfg, codec, extra_args,
            Path(args.srt) if args.srt else None,
            hwaccel,
            total_duration,
            args.debug
        )

        final_out = Path(args.output)
        if args.audio:
            af = Path(args.audio)
            if not af.exists():
                print(f"警告：找不到音频 {af}，跳过合并", file=sys.stderr)
                shutil.move(video_only, final_out)
            else:
                merge_audio_with_progress(
                    video_only, af, final_out,
                    total_duration, args.debug
                )
        else:
            shutil.move(video_only, final_out)

        print(f"✔ 完成：{final_out}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == '__main__':
    main()
