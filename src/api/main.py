import sys
import os
import uvicorn
import argparse
import glob

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import bootstrap
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# config and log are now initialized by bootstrap.py
from src.config_loader import config
from src.logger import log
from src.api.routers import (
    create_tasks,
    generate_audio,
    generate_scenes,
    generate_assets,
    generate_subtitles,
    generate_video,
    documentation,
)
from src.api.routers.yt import process_video, status, rewrite_manuscript # 导入新的 yt 子路由

# 导入用于设置信号处理器的函数，这是实现优雅关闭的关键
from src.core.process_manager import setup_signal_handlers

# --- FastAPI App Initialization ---
app = FastAPI(
    title="自动化视频生成 API",
    description='提供从脚本到视频的自动化生成流程的API接口。 <br><br> **[点击此处查看所有文档](/documentation)**',
    version="1.0.0"
)

# # Explicitly initialize LlmManager to ensure its initialization log is printed early
# # 备注：在采用“按需启动”服务模式后，此处的预加载检查已不再需要，并与优化目标冲突。
# # 因此，我们将其注释掉，以避免在应用启动时就强制加载LLM服务。
# from src.providers.llm import LlmManager
# llm_manager_instance = LlmManager(config)
# if not llm_manager_instance.get_provider():
#     log.error("LLM Manager failed to initialize. Please check config.yaml and LLM service status.")

# Mount the 'tasks' directory under a specific static path to avoid conflicts with API routes
app.mount("/static/tasks", StaticFiles(directory="tasks"), name="static_tasks")

# Include routers from other modules
app.include_router(create_tasks.router)
app.include_router(generate_audio.router)
app.include_router(generate_subtitles.router)
app.include_router(generate_scenes.router)
app.include_router(generate_assets.router)
app.include_router(generate_video.router)
app.include_router(documentation.router) # Add the documentation router
app.include_router(process_video.router, prefix="/yt", tags=["YouTube Subtitles"]) # YouTube 视频处理路由
app.include_router(status.router, prefix="/yt", tags=["YouTube Subtitles"]) # YouTube 任务状态路由
app.include_router(rewrite_manuscript.router, prefix="/yt", tags=["YouTube Subtitles"]) # YouTube 稿件重写路由

@app.get("/", tags=["Root"], include_in_schema=False)
async def read_root():
    return {"message": "Welcome to the Automatic Video Editing API!"}

# --- Server Startup Logic ---
if __name__ == "__main__":
    # --- 关键步骤: 设置信号处理器 ---
    # 在应用主入口调用此函数，以确保无论何时收到退出信号（如 Ctrl+C），
    # 应用都能先尝试干净地终止所有子进程，然后再退出。
    # 这是防止 "孤儿" ffmpeg 进程残留的关键。
    setup_signal_handlers()

    # Load default server settings from config
    api_config = config.get('api_server', {})
    default_host = api_config.get('host', '0.0.0.0')
    default_port = api_config.get('port', 8000)

    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(description="Run the Automatic Video Editing API server.")
    parser.add_argument("-H", "--host", type=str, default=default_host,
                        help=f"Host to bind the server to (default: {default_host})")
    parser.add_argument("-p", "--port", type=int, default=default_port,
                        help=f"Port to run the server on (default: {default_port})")
    parser.add_argument("--reload", action="store_true",
                        help="Enable auto-reload for development.")
    args = parser.parse_args()

    # To run this API server with custom settings:
    # python src/api/main.py --host 127.0.0.1 --port 8080 --reload
    log.info(f"启动 API 服务器于 {args.host}:{args.port} (自动重载: {'启用' if args.reload else '禁用'})")
    uvicorn.run("src.api.main:app", host=args.host, port=args.port, reload=args.reload)
