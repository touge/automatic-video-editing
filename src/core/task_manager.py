import os
from pathlib import Path
import uuid
from typing import Optional, Dict, Any
import json
import datetime
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
        "final_scenes_with_assets": "final_scenes_assets.json", # 新增：用于存储带有素材路径的场景数据
        "segments_cache": ".scenes/segments.json",
        "scenes_raw_cache": ".scenes/scenes_raw.json",
        # Scene Splitter
        "scene_split_chunk": ".scenes/scenes_split/chunk_{start}_{end}.json",
        # Video Composer
        "final_video": "final_video.mp4",
        "video_segment": ".videos/segments/seg_{index:04d}.mp4",
        "concat_list": ".videos/concat_list.txt",
        "concatenated_video": ".videos/video_only_concatenated.mp4",
        "video_with_audio": ".videos/video_with_audio.mp4",
        "progress_log": ".videos/progress_{name}.log",
        "temp_video_file": ".videos/temp/{name}",
    }

    # Define task statuses
    STATUS_PENDING = "PENDING"
    STATUS_RUNNING = "RUNNING"
    STATUS_SUCCESS = "SUCCESS"
    STATUS_FAILED = "FAILED"

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
        self._status_file_path = self.task_path / "status.json" # Define status file path

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

    def _get_status_file_path(self) -> Path:
        """Returns the path to the task's status file."""
        return self.task_path / "status.json"

    def update_task_status(self, status: str, step: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        """
        Updates the status of the task by reading the existing status and merging the new data.
        This ensures that persistent metadata like 'speaker' or 'video_style' is not lost.

        :param status: The new status of the task (e.g., PENDING, RUNNING, SUCCESS, FAILED).
        :param step: Optional string indicating the current major step of the task.
        :param details: Optional dictionary with additional details to be merged into the status.
        """
        # First, get the current state of the task.
        status_data = self.get_task_status()

        # Now, update it with the new information.
        status_data['status'] = status
        status_data['timestamp'] = self._get_current_timestamp()
        
        if step:
            status_data['step'] = step
        
        # Merge new details. This will add new keys or overwrite existing ones in the details.
        if details:
            status_data.update(details)

        # Write the updated status back to the file.
        with open(self._get_status_file_path(), 'w', encoding='utf-8') as f:
            json.dump(status_data, f, ensure_ascii=False, indent=4)

    def get_task_status(self) -> Dict[str, Any]:
        """
        Retrieves the current status of the task from the status file.
        Returns a dictionary with status information, or a default PENDING status if not found.
        """
        status_file = self._get_status_file_path()
        if status_file.exists():
            with open(status_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "task_id": self.task_id,
            "status": self.STATUS_PENDING,
            "message": "Task status file not found, assuming pending."
        }

    def _get_current_timestamp(self) -> str:
        """Helper method to get current timestamp in ISO format."""
        return datetime.datetime.now().isoformat()
