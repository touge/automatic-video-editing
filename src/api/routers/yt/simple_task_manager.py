from typing import Optional
from src.core.task_manager import TaskManager

class SimpleTaskManager(TaskManager):
    """
    A simplified TaskManager that does not create any cache directories upon initialization
    and adds a path for the paragraphs text file.
    """
    def __init__(self, task_id: Optional[str] = None):
        # Add the custom path for the manuscript file to the class's templates.
        if 'manuscript' not in self.PATH_TEMPLATES:
            self.PATH_TEMPLATES['manuscript'] = 'manuscript.txt'
        
        # Now, call the parent constructor.
        super().__init__(task_id)

    def _setup_cache_dirs(self):
        """
        Overrides the parent method to do nothing, preventing the creation of cache directories.
        """
        pass
