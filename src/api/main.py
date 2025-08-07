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
    generate_digital_human,
)
from src.api.routers.yt import process_video, status, rewrite_manuscript # 导入新的 yt 子路由

# 导入用于设置信号处理器的函数，这是实现优雅关闭的关键
from src.core.process_manager import setup_signal_handlers

# --- FastAPI 应用初始化 ---
app = FastAPI(
    title="Automated Video Generation API",
    description='API for automating the video generation process from script to final video. <br><br> **[Click here for all documentation](/documentation)**',
    version="1.0.0"
)

# # 启动事件回调（可选）
# @app.on_event("startup")
# async def on_startup():
#     port = config.get("api_server", {}).get("port", 8000)
#     log.info(f"✅ [Service Status] Auto-crop API started and listening on port {port}")


# 挂载 'tasks' 目录为一个静态文件路径，以避免与API路由冲突
# 这样就可以通过 /static/tasks/... 的URL访问任务文件夹中的文件
app.mount("/static/tasks", StaticFiles(directory="tasks"), name="static_tasks")

# 包含来自其他模块的路由
app.include_router(create_tasks.router)
app.include_router(generate_audio.router)
app.include_router(generate_subtitles.router)
app.include_router(generate_scenes.router)
app.include_router(generate_assets.router)
app.include_router(generate_video.router)
app.include_router(documentation.router) # 文档路由
app.include_router(generate_digital_human.router) # 数字人视频生成路由
app.include_router(process_video.router, prefix="/yt", tags=["YouTube Subtitles"]) # YouTube 视频处理路由
app.include_router(status.router, prefix="/yt", tags=["YouTube Subtitles"]) # YouTube 任务状态路由
app.include_router(rewrite_manuscript.router, prefix="/yt", tags=["YouTube Subtitles"]) # YouTube 稿件重写路由

# 根路径，用于简单的服务健康检查
@app.get("/", tags=["Root"], include_in_schema=False)
async def read_root():
    return {"message": "Welcome to the Automated Video Generation API!"}

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

    # 启动服务器的示例命令:
    # python src/api/main.py --host 127.0.0.1 --port 8080 --reload
    log.info(f"Starting API server at {args.host}:{args.port} (Auto-reload: {'enabled' if args.reload else 'disabled'})")
    uvicorn.run("src.api.main:app", host=args.host, port=args.port, reload=args.reload)
