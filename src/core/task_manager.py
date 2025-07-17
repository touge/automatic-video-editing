import os
from pathlib import Path
import uuid
from typing import Optional
import bootstrap  # Ensure config is loaded before this module is used
from src.config_loader import config

class TaskManager:
    """
    Manages the lifecycle and file paths for a single task using a centralized,
    dynamic path registry for cross-platform robustness and maintainability.
    """
    PATH_TEMPLATES = {
        # Audio Preprocessor
        "final_audio": "final_audio.wav",
        "original_doc": ".documents/original.txt",
        "audio_segment": ".audios/segments/{index}.wav",
        "tts_audio": ".audios/tts_cache/{name}.wav",
        "doc_segment": ".documents/segments/{index}.txt",
        # Subtitles
        "final_srt": "final.srt",
        "sentences": ".documents/sentences.txt",
        "whisper_cache": ".whisper/transcription.json",
        "alignment_cache": ".whisper/aligned.pkl",
        # Scene Generator
        "final_scenes": "final_scenes.json",
        "segments_cache": ".scenes/segments.json",
        "scenes_raw_cache": ".scenes/scenes_raw.json",
        # Scene Splitter
        "scene_split_chunk": ".scenes/scenes_split/chunk_{start}_{end}.json",
        # Video Composer
        "final_video": "final_video.mp4",
        "video_segment": ".videos/seg_{index:04d}.mp4",
        "concat_list": ".videos/concat_list.txt",
        "concatenated_video": ".videos/video_only_concatenated.mp4",
        "video_with_audio": ".videos/video_with_audio.mp4",
        "progress_log": ".videos/progress_{name}.log",
    }

    def __init__(self, task_id: Optional[str] = None):
        paths_config = config.get('paths', {})
        self._base_path = Path(paths_config.get('task_folder', 'storage/tasks'))
        
        if task_id:
            self.task_id = task_id
            self.is_new = False
        else:
            self.task_id = self._generate_task_id()
            self.is_new = True
        
        self.task_path = self._ensure_task_path()
        self._setup_cache_dirs()

    @staticmethod
    def _generate_task_id() -> str:
        return str(uuid.uuid4())

    def get_task_path(self) -> Path:
        return self._base_path / self.task_id

    def _ensure_task_path(self) -> Path:
        path = self.get_task_path()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _setup_cache_dirs(self):
        """Creates all necessary cache directories for a task."""
        parent_dirs = {Path(template).parent for template in self.PATH_TEMPLATES.values() if '/' in template or '\\' in template}
        for parent in parent_dirs:
            (self.task_path / parent).mkdir(parents=True, exist_ok=True)

    def get_file_path(self, key: str, **kwargs) -> str:
        """
        Gets the full path for a file or directory from the template registry.
        Ensures the parent directory exists and returns a POSIX-style path string.
        """
        template = self.PATH_TEMPLATES.get(key)
        if not template:
            raise KeyError(f"Path key '{key}' not defined in TaskManager.PATH_TEMPLATES.")
        
        relative_path_str = template.format(**kwargs)
        full_path = self.task_path / relative_path_str
        
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        return full_path.as_posix()

    def save_script(self, script_content: bytes) -> str:
        """
        Saves the provided script content to the designated script file for the task.

        :param script_content: The content of the script as bytes.
        :return: The path to the saved script file.
        """
        script_path_str = self.get_file_path('original_doc')
        with open(script_path_str, 'wb') as f:
            f.write(script_content)
        return script_path_str
