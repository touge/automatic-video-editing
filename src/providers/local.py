import os
import random
from pathlib import Path
from typing import List, Dict, Any

from .base import BaseVideoProvider

class LocalProvider(BaseVideoProvider):
    """
    从本地文件夹搜索视频的提供者。
    """
    def __init__(self, config: dict):
        paths_config = config.get('paths', {})
        self.local_assets_dir = paths_config.get('local_assets_dir', 'assets/local')
        self.video_extensions = {'.mp4', '.mov', '.avi', '.mkv'} # 支持的视频文件扩展名

    def search(self, keywords: List[str], count: int = 1) -> List[Dict[str, Any]]:
        """
        在本地素材目录中搜索文件名包含关键词的视频。
        """
        if not os.path.isdir(self.local_assets_dir):
            return []

        # 递归地查找所有视频文件
        all_videos = []
        for root, _, files in os.walk(self.local_assets_dir):
            for file in files:
                if Path(file).suffix.lower() in self.video_extensions:
                    all_videos.append(Path(root) / file)
        
        # 查找匹配关键词的视频
        matched_videos = {video_path for keyword in keywords for video_path in all_videos if keyword.lower() in video_path.name.lower()}
        
        if not matched_videos:
            return []
        
        # 随机选择所需数量的视频
        num_to_select = min(count, len(matched_videos))
        selected_paths = random.sample(list(matched_videos), num_to_select)

        return self._standardize_results(selected_paths)

    def _standardize_results(self, video_paths: List[Path]) -> List[Dict[str, Any]]:
        """将本地文件路径标准化。"""
        return [{
            'id': f"local-{path.name}",
            'download_url': str(path.resolve()), # 对于本地文件，"download_url" 就是它的绝对路径
            'source': 'local',
            'description': f"Local asset: {path.name}"
        } for path in video_paths]

