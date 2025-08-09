import subprocess
import os
import json

class VideoCompositor:
    """
    一个用于处理和合成视频的类。
    V5.0 (Final): 优化API，使用 position: {'x', 'y'} 结构。
    """

    def __init__(self):
        pass

    def _run_ffmpeg_command(self, command, description):
        print(f"--- {description} ---")
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', bufsize=1)
            for line in process.stdout:
                print(line, end='', flush=True)
            process.wait()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, command)
            print(f"\n✅ {description} 完成")
            return True
        except Exception as e:
            print(f"\n❌ 执行 FFmpeg 命令时出错: {e}")
            return False

    def get_video_info(self, path):
        if not os.path.exists(path):
            print(f"文件不存在: {path}")
            return None
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=duration,width,height', '-of', 'json', path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)['streams'][0]
            return {'duration': float(info.get('duration', 0)), 'width': int(info.get('width', 0)), 'height': int(info.get('height', 0))}
        except Exception as e:
            print(f"获取视频信息失败 {path}: {e}")
            return None

    def process_short_video(self, input_path, output_path, background_path, volume_multiplier=1.0,
                            chroma_key_color='0x76e24f', chroma_key_similarity='0.09', chroma_key_blend='0.1',
                            scale_ratio=0.95, x_pos=130, y_pos=40):
        video_info = self.get_video_info(input_path)
        if not video_info: return False
        scaled_width = int(video_info['width'] * scale_ratio)
        scaled_height = int(video_info['height'] * scale_ratio)
        filter_complex = (
            f"[1:v]chromakey={chroma_key_color}:{chroma_key_similarity}:{chroma_key_blend},setsar=1,"
            f"scale={scaled_width}:{scaled_height}[fg];"
            f"[0:v]scale={video_info['width']}:{video_info['height']}[bg];"
            f"[bg][fg]overlay=x={x_pos}:y={y_pos}[outv];"
            f"[1:a]volume={volume_multiplier}[outa]"
        )
        command = ['ffmpeg', '-y', '-i', background_path, '-i', input_path, '-filter_complex', filter_complex,
                   '-map', '[outv]', '-map', '[outa]', '-c:v', 'h264_nvenc', '-c:a', 'aac', '-shortest', output_path]
        return self._run_ffmpeg_command(command, f"处理 {os.path.basename(input_path)}")

    def composite_videos(self, base_video_path, short_videos, output_path, clip_params=None, base_volume=1.0):
        print(f"\n开始合成最终视频 (V5.0): {output_path}")
        base_info = self.get_video_info(base_video_path)
        if not base_info: return False

        command = ['ffmpeg', '-y']
        if clip_params and 'start' in clip_params:
            command.extend(['-ss', str(clip_params['start'])])
        command.extend(['-i', base_video_path])

        base_duration = float(clip_params.get('duration')) if clip_params and 'duration' in clip_params else base_info['duration']
        
        filter_complex_parts = []
        audio_mix_inputs = []
        
        if base_volume > 0:
            filter_complex_parts.append(f"[0:a]volume={base_volume}[base_a];")
            audio_mix_inputs.append("[base_a]")

        overlay_input = "[0:v]"
        for i, video_spec in enumerate(short_videos, 1):
            path = video_spec['path']
            if not os.path.exists(path): continue
            command.extend(['-i', path])

            short_info = self.get_video_info(path)
            if not short_info: continue

            s_clip = video_spec.get('clip_params', {})
            s_clip_start = s_clip.get('start', 0)
            s_clip_duration = s_clip.get('duration', short_info['duration'] - s_clip_start)

            start_time = video_spec['start_time']
            if start_time is None:
                start_time = base_duration - s_clip_duration
            elif isinstance(start_time, (int, float)) and start_time < 0:
                start_time = base_duration + start_time
            
            end_time = start_time + s_clip_duration

            video_stream_name = f"v{i}"
            trim_filter = f"trim=start={s_clip_start}:duration={s_clip_duration}"
            filter_chain = f"[{i}:v]{trim_filter},setpts=PTS-STARTPTS+{start_time}/TB[{video_stream_name}_t];"
            filter_chain += f"[{video_stream_name}_t]scale={video_spec.get('size', 'iw:ih')}[{video_stream_name}];"
            filter_complex_parts.append(filter_chain)
            
            # --- V5 API 优化 ---
            position = video_spec.get('position', {})
            x_pos = position.get('x', "(W-w)/2")
            y_pos = position.get('y', "(H-h)/2")
            # --- V5 API 优化结束 ---
            
            overlay_output = f"[tmp{i}]" if i < len(short_videos) else "[v_out]"
            filter_complex_parts.append(
                f"{overlay_input}[{video_stream_name}]overlay=x={x_pos}:y={y_pos}:enable='between(t,{start_time},{end_time})'{overlay_output};"
            )
            overlay_input = f"[tmp{i}]"

            s_volume = video_spec.get('volume')
            if s_volume and s_volume > 0:
                audio_stream_name = f"a{i}"
                delay_ms = int(start_time * 1000)
                audio_filter = (
                    f"[{i}:a]atrim=start={s_clip_start}:duration={s_clip_duration},asetpts=PTS-STARTPTS,"
                    f"adelay={delay_ms}|{delay_ms},volume={s_volume}[{audio_stream_name}];"
                )
                filter_complex_parts.append(audio_filter)
                audio_mix_inputs.append(f"[{audio_stream_name}]")

        final_video_map = "[v_out]" if short_videos else "[0:v]"

        if len(audio_mix_inputs) > 1:
            mix_filter = f"{''.join(audio_mix_inputs)}amix=inputs={len(audio_mix_inputs)}:dropout_transition=0[a_mix];"
            filter_complex_parts.append(mix_filter)
            final_audio_input = "[a_mix]"
        elif len(audio_mix_inputs) == 1:
            final_audio_input = audio_mix_inputs[0]
        else:
            final_audio_input = None

        final_audio_map = final_audio_input
        if final_audio_input and clip_params and 'duration' in clip_params:
            filter_complex_parts.append(f"{final_audio_input}atrim=duration={clip_params['duration']}[a_final];")
            final_audio_map = "[a_final]"

        final_filter_complex = "".join(filter_complex_parts).rstrip(';')
        
        command.extend(['-filter_complex', final_filter_complex, '-map', final_video_map])
        if final_audio_map:
            command.extend(['-map', final_audio_map])
        
        command.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-shortest', output_path])
        if clip_params and 'duration' in clip_params:
             command.extend(['-t', str(clip_params['duration'])])

        return self._run_ffmpeg_command(command, "合成所有视频")
