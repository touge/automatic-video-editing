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
    script_path = "analysis.py"
    command = ["python", script_path, "--srt-file", srt_path]
    
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
            # 脚本成功执行但输出不符合预期，包含 stderr 以便调试
            error_details = f"STDOUT: {output}\nSTDERR: {result.stderr}"
            raise RuntimeError(f"无法从阶段一脚本的输出中解析任务ID。脚本输出详情:\n{error_details}")
            
    except subprocess.CalledProcessError as e:
        # 脚本执行失败（非零退出码），包含 stdout 和 stderr
        error_details = f"STDOUT: {e.stdout}\nSTDERR: {e.stderr}"
        raise RuntimeError(f"阶段一脚本执行失败 (exit code {e.returncode})。\n{error_details}")
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

    # 建议：在生产环境中使用更强大的日志记录工具，例如 Python 的 logging 模块
    print(f"后台任务启动：开始执行视频合成命令: {' '.join(command)}")
    try:
        # 注意：capture_output=True 可能会在长时间运行的脚本中消耗大量内存来缓冲输出。
        # 如果脚本输出不是必须捕获的，可以移除它以优化性能。
        result = subprocess.run(command, check=True, text=True, encoding='utf-8', capture_output=True)
        print(f"后台任务成功: 任务 {task_id} 的视频合成已完成。")
    except subprocess.CalledProcessError as e:
        print(f"后台任务失败: 任务 {task_id} 的视频合成失败。\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}")
    finally:
        # 使用 finally 块确保无论成功还是失败，上传的临时文件都能被可靠地清理
        if os.path.exists(audio_path):
            os.remove(audio_path)
        if subtitle_path and os.path.exists(subtitle_path):
            os.remove(subtitle_path)
        print(f"后台任务清理: 任务 {task_id} 的临时文件已被清理。")
