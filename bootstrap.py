# bootstrap.py
import sys
import os

# 添加项目根
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 显式导入并初始化配置和日志系统
# 确保这些在其他模块（如LlmManager）被导入之前执行
from src.config_loader import config
from src.logger import log

log.info("Bootstrap: Configuration and logging system initialized.")

'''

ffmpeg -i idx_1.wav -ac 1 -ar 16000 idx_1_16000.wav

python -m aeneas.tools.execute_task idx_1_16000.wav idx_1.txt "task_language=zho|os_task_file_format=srt|is_text_type=plain" map.srt


python -m aeneas.tools.execute_task idx_1_16000.wav idx_1.txt "task_language=zho|os_task_file_format=json|is_text_type=plain" map.srt --verbose



'''
