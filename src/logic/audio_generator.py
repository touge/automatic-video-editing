"""
AudioGenerator 是一个用于从文本生成配音音频的自动化处理类，构成 AI 视频生成流程中的音频合成子模块。

核心功能：
- 支持按段落智能分割文稿，并控制段落时长（scene_target_length）
- 使用 TTS 模块将每段文字转为音频，支持 URL 下载或本地路径迁移
- 自动合成多个语音段，输出最终音频文件（WAV 格式）
- 支持任务上下文管理与多阶段缓存，配合 TaskManager 提供路径管理
- 提供错误日志记录与异常回溯机制，保障稳定性

适用场景：
适用于“先文本后语音”生成流程，如讲解类视频、科普内容、虚拟角色配音等内容管线。

依赖模块：
- config_loader：加载 TTS 参数与分段长度配置
- tts：TTS 文本转语音服务（可插件化调用）
- task_manager：管理任务路径和文件命名
- AudioSegment（pydub）：处理音频合并与导出
- tqdm：实时显示处理进度条
"""
import os
import shutil
import requests
from tqdm import tqdm
from typing import List, Dict, Optional
from pydub import AudioSegment

from src.logger import log
# ✅ 修改：导入 get_tts_instance 工厂函数，而不是全局实例
from src.tts import get_tts_instance
from src.config_loader import config
from src.core.task_manager import TaskManager

class AudioGenerator:
    def __init__(self, task_id: str, doc_file: str, speaker: Optional[str] = None):
        if not task_id or not doc_file:
            raise ValueError("task_id and doc_file must be provided.")
        if not os.path.exists(doc_file):
            raise FileNotFoundError(f"Document file not found at '{doc_file}'")

        self.task_manager = TaskManager(task_id)
        self.doc_file = doc_file
        
        # 从配置加载参数
        self.tts_config = config.get('tts_providers', {})
        text_processing_config = config.get('text_processing', {})
        
        self.tts_max_chunk_length = self.tts_config.get('tts_max_chunk_length', 2000)
        self.scene_target_length = text_processing_config.get('scene_target_length', 300)
        
        self.speaker = self._resolve_speaker(speaker)

        self.final_audio = self.task_manager.get_file_path('final_audio')

    def _resolve_speaker(self, speaker: Optional[str]) -> str:
        """根据 speaker 从配置中解析出实际的 speaker 值。"""
        provider_name = self.tts_config.get('use')
        if not provider_name:
            raise ValueError("No TTS provider specified in config ('tts_providers.use').")
            
        provider_config = self.tts_config.get(provider_name)
        if not provider_config:
            raise ValueError(f"Configuration for TTS provider '{provider_name}' not found.")
            
        speakers = provider_config.get('speakers')
        if not isinstance(speakers, dict) or not speakers:
            raise ValueError(f"'speakers' dictionary not found or is empty for provider '{provider_name}'.")
            
        # 如果提供了 speaker 并且它存在于 speakers 字典中，则使用它
        if speaker and speaker in speakers:
            selected_speaker = speakers[speaker]
            log.info(f"Using specified speaker '{speaker}': {selected_speaker}")
            return selected_speaker
        
        # 否则，使用默认的 speaker
        default_speaker = speakers.get('default')
        if not default_speaker:
            raise ValueError(f"'default' speaker not found in 'speakers' for provider '{provider_name}'.")
        
        log.info(f"Using default speaker: {default_speaker}")
        return default_speaker

    def run(self):
        log.info(f"--- Starting Text-First Audio Preprocessing for Task ID: {self.task_manager.task_id} ---")
        
        try:
            # 1. 从原始文稿进行两级分段
            segment_text = self._segment_document(self.doc_file)
            if not segment_text:
                raise ValueError("Document segmentation failed.")
            # print(f"segment_text: \n{ segment_text}")

            # 分段合成音频
            self._synthesize_audio_segments(segment_text)

            final_audio_path = self.task_manager.get_file_path('final_audio')
            if os.path.exists(final_audio_path):
                log.info(f"Final audio already exists, skipping combination: {final_audio_path}")
            else:
                if not self._combine_audio_segments(len(segment_text), final_audio_path):
                    raise RuntimeError("Failed to combine audio segments.")

            log.success("Text-first audio preprocessing pipeline completed successfully.")

        except Exception as e:
            log.error(f"Audio preprocessing pipeline failed: {e}", exc_info=True)
            raise

    def _segment_document(self, doc_file: str) -> List[Dict]:
        log.info("--- Step 1: Segmenting document---")
        with open(doc_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 按自然段落分割原始内容，并去除空行及两端空白
        paragraphs = [p.strip() for p in content.split('\n') if p.strip()]

        scene_chunks = []            # 存储切分后的场景段落列表
        current_scene_chunk = ""     # 当前正在构建的场景段落

        # 智能合并或切分段落，使其长度接近 scene_target_length 目标值
        for p in paragraphs:
            if not current_scene_chunk:
                # 当前段为空，初始化为当前段落
                current_scene_chunk = p
            elif len(current_scene_chunk) + len(p) < self.scene_target_length * 1.5:  # 合并阈值，允许稍微超出目标长度
                # 当前段与新段落合并不会超过阈值，则合并
                current_scene_chunk += "\n" + p
            else:
                # 超出阈值，将当前段存入结果列表，并重新开始新段
                scene_chunks.append(current_scene_chunk)
                current_scene_chunk = p

        # 加入最后一个未处理的段落（如果有）
        if current_scene_chunk:
            scene_chunks.append(current_scene_chunk)

        return scene_chunks

    def _synthesize_audio_segments(self, segments: List[str]):
        log.info("--- Step 2.2: Synthesizing audio for each segment ---")
        
        tts_kwargs = {
            'task_id': self.task_manager.task_id,
            'speaker': self.speaker
        }

        for i, segment_text in enumerate(tqdm(segments, desc="Synthesizing Audio")):
            audio_segment_path = self.task_manager.get_file_path('audio_segment', index=i)
            if os.path.exists(audio_segment_path):
                continue
            
            try:
                # ✅ 修改：通过 get_tts_instance() 获取实例并调用
                # Pass the combined kwargs to the synthesis function
                response = get_tts_instance().synthesize(segment_text, **tts_kwargs)
                
                # 检查是返回了URL还是本地路径
                if 'url' in response and response['url']:
                    # 如果是URL，下载文件
                    if not self._download_file(response['url'], audio_segment_path):
                        log.error(f"Failed to download audio for segment {i} from URL: {response['url']}")
                elif 'path' in response and response['path']:
                    # 如果是本地路径，直接移动或复制文件
                    shutil.move(response['path'], audio_segment_path)
                    log.info(f"Moved synthesized audio for segment {i} to final location.")
                else:
                    log.error(f"TTS response for segment {i} is invalid: {response}")

            except Exception as e:
                log.error(f"An error occurred during synthesis for segment {i}: {e}", exc_info=True)
                # Re-raise the exception to halt the process
                raise
        
        log.success("Finished synthesizing all segments.")

    def _combine_audio_segments(self, num_segments: int, output_path: str) -> bool:
        log.info("\n--- Step 2.3: Combining all audio segments ---")
        valid_audio_files = [self.task_manager.get_file_path('audio_segment', index=i) for i in range(num_segments) if os.path.exists(self.task_manager.get_file_path('audio_segment', index=i))]
        if not valid_audio_files:
            log.error("No audio files were generated to combine.")
            return False
        if len(valid_audio_files) != num_segments:
            log.warning("Some audio segments failed to generate and will be skipped.")
        try:
            combined_audio = sum(AudioSegment.from_wav(f) for f in tqdm(valid_audio_files, desc="Combining Audio"))
            combined_audio.export(output_path, format="wav")
            log.success(f"All audio segments combined successfully to: {output_path}")
            return True
        except Exception as e:
            log.error(f"Failed to combine audio files: {e}")
            return False
        
    def _download_file(self, url: str, destination: str) -> bool:
        """
        Helper function to download a file from a URL.
        """
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with open(destination, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except requests.exceptions.RequestException as e:
            log.error(f"Error downloading {url}: {e}")
            return False
