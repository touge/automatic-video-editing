# bootstrap.py
import sys
import os

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 🔧 你还可以在这里做更多初始化（如 dotenv、日志等）


'''

ffmpeg -i idx_1.wav -ac 1 -ar 16000 idx_1_16000.wav

python -m aeneas.tools.execute_task idx_1_16000.wav idx_1.txt "task_language=zho|os_task_file_format=srt|is_text_type=plain" map.srt


python -m aeneas.tools.execute_task idx_1_16000.wav idx_1.txt "task_language=zho|os_task_file_format=json|is_text_type=plain" map.srt --verbose



'''