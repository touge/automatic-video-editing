import sys
import os
import uvicorn
import argparse

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import bootstrap
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
# config and log are now initialized by bootstrap.py
from src.config_loader import config # Keep config import for now, as it's used directly below
from src.logger import log # Keep log import for now, as it's used directly below
from src.api.routers import tasks, analysis, composition, audio_tasks, subtitle_tasks # Import new routers

# --- FastAPI App Initialization ---
app = FastAPI(
    title="自动化视频生成 API",
    description="提供从脚本到视频的自动化生成流程的API接口。",
    version="1.0.0"
)

# Explicitly initialize LlmManager to ensure its initialization log is printed early
from src.providers.llm import LlmManager
llm_manager_instance = LlmManager(config)
if not llm_manager_instance.get_provider():
    log.error("LLM Manager failed to initialize. Please check config.yaml and LLM service status.")
    # Depending on criticality, you might want to sys.exit(1) here or raise an exception
    # For now, we'll just log an error and let the app continue, but LLM-dependent features will fail.

# Mount the 'tasks' directory under a specific static path to avoid conflicts with API routes
app.mount("/static/tasks", StaticFiles(directory="tasks"), name="static_tasks")

# Include routers from other modules
app.include_router(tasks.router)
app.include_router(analysis.router)
app.include_router(composition.router)
app.include_router(audio_tasks.router) # Include the new audio_tasks router
app.include_router(subtitle_tasks.router) # Include the new subtitle_tasks router

@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the Automatic Video Editing API!"}

# --- Server Startup Logic ---
if __name__ == "__main__":
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
