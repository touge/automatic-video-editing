import os
import shutil
import uuid
import subprocess
import re
from fastapi import UploadFile

UPLOADS_DIR = "storage/uploads"
os.makedirs(UPLOADS_DIR, exist_ok=True)

def save_upload_file(upload_file: UploadFile) -> str:
    """保存上传的文件并返回其路径"""
    try:
        # 使用UUID确保文件名唯一
        file_extension = os.path.splitext(upload_file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(UPLOADS_DIR, unique_filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
        return file_path
    finally:
        upload_file.file.close()

def run_stage_1_and_get_task_id(srt_path: str) -> str:
    """
    通过子进程调用阶段一脚本，并从其输出中解析task_id。
    如果失败则抛出异常。
    """
    script_path = "run_stage_1_analysis.py"
    command = ["python", script_path, "--with-subtitles", srt_path]
    
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, encoding='utf-8'
        )
        output = result.stdout
        print("--- Stage 1 script stdout ---\n", output)
        # 从脚本输出中用正则表达式匹配任务ID
        match = re.search(r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", output)
        
        if match:
            task_id = match.group(1)
            print(f"成功解析到任务ID: {task_id}")
            return task_id
        else:
            raise RuntimeError(f"无法从阶段一脚本的输出中解析任务ID。脚本输出: {output}")
            
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"阶段一脚本执行失败: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError(f"找不到脚本 {script_path}。请确保从项目根目录运行API服务器。")

def composition_task_wrapper(task_id: str, audio_path: str, subtitle_path: str | None):
    """
    一个包装函数，用于在后台通过子进程调用阶段二脚本。
    这个函数是为FastAPI的BackgroundTasks设计的。
    """
    script_path = "run_stage_2_composition.py"
    command = [
        "python", script_path,
        "--with-task-id", task_id,
        "--with-audio", audio_path,
    ]
    
    if subtitle_path:
        command.extend(["--with-subtitles", subtitle_path])

    print(f"在后台执行合成任务: {' '.join(command)}")
    try:
        subprocess.run(command, check=True, text=True, encoding='utf-8', capture_output=True)
        print(f"任务 {task_id} 的后台合成任务已完成。")
    except subprocess.CalledProcessError as e:
        print(f"错误: 任务 {task_id} 的后台合成任务失败。\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}")
    finally:
        # 清理上传的临时文件
        if os.path.exists(audio_path):
            os.remove(audio_path)
        if subtitle_path and os.path.exists(subtitle_path):
            os.remove(subtitle_path)

