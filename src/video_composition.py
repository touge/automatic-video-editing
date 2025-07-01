import ffmpeg

def assemble_video(scene_clips: list, original_video_path: str, output_path: str):
    """
    将视频片段和音频合成为最终视频 (使用 ffmpeg-python)。
    :param scene_clips: 包含视频片段信息的列表，每个元素是(路径, 时长)
    :param original_video_path: 带有原始音频的视频文件路径
    :param output_path: 输出视频文件路径
    """
    print("开始使用 ffmpeg-python 合成最终视频...")

    # 目标视频参数 (可以根据需要调整或放入配置文件)
    width = 1920
    height = 1080
    framerate = 30
    
    # 1. 为每个场景创建经过裁剪和标准化的视频流
    video_parts = []
    for path, duration in scene_clips:
        stream = ffmpeg.input(path, t=duration)
        # 标准化分辨率和帧率，以确保可以拼接
        video_stream = (
            stream.video
            .filter('scale', width=width, height=height, force_original_aspect_ratio='decrease')
            .filter('pad', width=width, height=height, x='(ow-iw)/2', y='(oh-ih)/2', color='black')
            .filter('fps', fps=framerate, round='up')
        )
        video_parts.append(video_stream)

    # 2. 拼接所有标准化的视频流 (v=1 表示1个视频输出, a=0 表示0个音频输出)
    concatenated_video = ffmpeg.concat(*video_parts, v=1, a=0).node[0]
    
    # 3. 从原始视频中提取原始音轨
    original_audio = ffmpeg.input(original_video_path).audio

    # 4. 将拼接好的视频与原始音轨合并
    (
        ffmpeg
        .output(concatenated_video, original_audio, output_path, vcodec='libx264', acodec='aac', strict='-2', loglevel='warning')
        .run(overwrite_output=True)
    )
    print(f"视频合成完毕，已保存至: {output_path}")
