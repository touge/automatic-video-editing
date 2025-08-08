from src.core.task_manager import TaskManager

class RewriteTaskManager(TaskManager):
    """
    一个专门用于文稿重写任务的轻量级任务管理器。

    它继承自核心的 TaskManager，复用了状态文件的读写逻辑，
    但重写了目录设置方法，以避免为这个简单的任务创建不必要的子目录。
    """
    def _setup_cache_dirs(self):
        """
        重写此方法，使其不创建任何缓存目录。
        重写任务只需要一个 status.json 文件。
        """
        pass
