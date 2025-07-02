#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import subprocess
import sys
import shutil
import tempfile
import argparse
from pathlib import Path
from tqdm import tqdm

def detect_video_encoder():
    """
    检测可用编码器，返回 (codec, extra_args, needs_hwaccel)
    """
    try:
        out = subprocess.run(
            ['ffmpeg', '-hide_banner', '-encoders'],
            capture_output=True, text=True, check=True
        ).stdout.lower()
    except Exception:
        return 'libx264', ['-preset', 'veryfast'], False

    if 'h264_nvenc' in out:
        return 'h264_nvenc', ['-preset', 'p2'], False
    if 'h264_qsv' in out:
        return 'h264_qsv', [], True
    if 'h264_videotoolbox' in out:
        return 'h264_videotoolbox', [], False
    return 'libx264', ['-preset', 'veryfast'], False

def run_cmd(cmd, debug):
    """
    统一执行子进程，依据 debug 决定是否输出详细日志
    """
    if debug:
        subprocess.run(cmd, check=True)
    else:
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)

def trim_segment(src, dur, dst, codec, extra, hwaccel, debug):
    """
    裁剪前 dur 秒并转码到 dst
    """
    cmd = ['ffmpeg', '-y']
    if hwaccel and 'qsv' in codec:
        cmd += ['-hwaccel', 'qsv']
    cmd += [
        '-ss', '0',
        '-t', str(dur),
        '-i', str(src),
        '-c:v', codec, *extra,
        '-c:a', 'aac',
        str(dst)
    ]
    run_cmd(cmd, debug)

def make_concat_list(segments, list_path):
    """
    写 list.txt 给 concat demuxer
    """
    with open(list_path, 'w', encoding='utf-8') as f:
        for seg in segments:
            f.write(f"file '{seg.as_posix()}'\n")

def concat_segments(list_txt, out_mp4, codec, extra, srt, hwaccel, debug):
    """
    根据 list.txt 拼接，外挂字幕时重编码，否则流拷贝
    """
    if srt and srt.exists():
        cmd = [
            'ffmpeg', '-y',
            '-fflags', '+genpts',
            '-f', 'concat', '-safe', '0', '-i', str(list_txt),
            '-vf', f"subtitles={srt.as_posix()}",
            '-c:v', codec, *extra,
            '-c:a', 'aac',
            str(out_mp4)
        ]
    else:
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', str(list_txt),
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero',
            str(out_mp4)
        ]

    if hwaccel and 'qsv' in codec:
        cmd.insert(1, '-hwaccel')
        cmd.insert(2, 'qsv')

    run_cmd(cmd, debug)

def merge_audio(video_mp4, audio_file, final_mp4, debug):
    """
    合并外部音频到视频
    """
    cmd = [
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
    run_cmd(cmd, debug)

def main():
    p = argparse.ArgumentParser(
        description="精确按 duration_parts 裁剪+拼接视频，支持外挂 SRT & 合并音频"
    )
    p.add_argument('-j', '--scenes', default='scenes.json',
                   help="场景 JSON 文件")
    p.add_argument('-s', '--srt', help="外挂 SRT 文件（可选）")
    p.add_argument('-a', '--audio', help="外挂音频文件（可选）")
    p.add_argument('-o', '--output', default='output.mp4',
                   help="最终输出文件")
    p.add_argument('--debug', action='store_true',
                   help="开启调试模式，输出详细日志，禁用进度条")
    args = p.parse_args()

    # 读取并验证场景
    scenes_file = Path(args.scenes)
    if not scenes_file.exists():
        sys.exit(f"错误：找不到 {scenes_file}")
    data = json.loads(scenes_file.read_text(encoding='utf-8'))
    if not data:
        sys.exit("错误：场景数据为空")

    scene = data[0]
    assets    = [Path(x) for x in scene.get('asset_paths', [])]
    durations = scene.get('duration_parts', [])
    if len(assets) != len(durations):
        sys.exit("错误：asset_paths 与 duration_parts 数量不一致")

    # 检测编码器
    codec, extra_args, hwaccel = detect_video_encoder()
    if args.debug:
        print(f"[DEBUG] codec={codec}, hwaccel={hwaccel}, extra={extra_args}")

    # 临时目录
    tmpdir = Path(tempfile.mkdtemp(prefix='vid_proc_'))
    segs = []
    try:
        # 步骤1: 裁剪各段
        if args.debug:
            print("[DEBUG] 开始裁剪各段 …")
            for i, (src, dur) in enumerate(zip(assets, durations)):
                dst = tmpdir / f"seg_{i:02d}.mp4"
                trim_segment(src, dur, dst, codec, extra_args, hwaccel, True)
                segs.append(dst)
        else:
            with tqdm(total=len(assets), desc="裁剪视频片段", unit="段") as pbar:
                for i, (src, dur) in enumerate(zip(assets, durations)):
                    dst = tmpdir / f"seg_{i:02d}.mp4"
                    trim_segment(src, dur, dst, codec, extra_args, hwaccel, False)
                    segs.append(dst)
                    pbar.update(1)

        if not segs:
            sys.exit("错误：未生成任何裁剪片段")

        # 步骤2: 生成 list.txt 并拼接
        list_txt = tmpdir / "list.txt"
        make_concat_list(segs, list_txt)

        video_only = tmpdir / "video_only.mp4"
        if args.debug:
            print("[DEBUG] 开始拼接段 …")
            concat_segments(list_txt, video_only, codec,
                            extra_args, Path(args.srt) if args.srt else None,
                            hwaccel, True)
        else:
            tqdm.write("拼接视频中 …")
            concat_segments(list_txt, video_only, codec,
                            extra_args, Path(args.srt) if args.srt else None,
                            hwaccel, False)

        # 步骤3: 合并音频
        final_out = Path(args.output)
        if args.audio:
            audio_file = Path(args.audio)
            if not audio_file.exists():
                tqdm.write(f"警告：找不到音频 {audio_file}，跳过合并")
                shutil.move(str(video_only), str(final_out))
            else:
                if args.debug:
                    print("[DEBUG] 开始合并音频 …")
                    merge_audio(video_only, audio_file, final_out, True)
                else:
                    tqdm.write("合并音频中 …")
                    merge_audio(video_only, audio_file, final_out, False)
        else:
            shutil.move(str(video_only), str(final_out))

        print(f"完成：{final_out}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

if __name__ == '__main__':
    main()
