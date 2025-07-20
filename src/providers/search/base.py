from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseVideoProvider(ABC):
    """
    视频提供者的抽象基类。
    定义了所有视频源（如 Pexels, Pixabay, 本地文件等）必须遵循的统一接口。
    """

    def __init__(self):
        self.enabled = True

    @abstractmethod
    def search(self, keywords: List[str], count: int = 1, min_duration: float = 0) -> List[Dict[str, Any]]:
        """
        根据关键词搜索视频。

        Args:
            keywords (List[str]): 用于搜索的关键词列表。
            count (int): 希望获取的视频数量。
            min_duration (float): 视频的最短时长（秒）。

        Returns:
            List[Dict[str, Any]]: 一个包含视频信息的字典列表。
                                  每个字典应包含标准化的键，例如：
                                  {'id': '...', 'download_url': '...', 'source': 'pexels', ...}
        """
        pass
