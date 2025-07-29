import asyncio
from typing import Dict, Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from src.config_loader import config
from src.api.security import verify_token
from src.api.routers.yt.shared_data import tasks # 导入共享的 tasks 字典
from src.providers.llm import LlmManager # 导入 LLM 管理器
from src.logger import log # 导入日志

router = APIRouter()

class RewriteManuscriptRequest(BaseModel):
    task_id: str
    # 可以添加更多重写参数，例如 target_style: Optional[str] = None
    # target_length: Optional[int] = None

class RewriteManuscriptResponse(BaseModel):
    task_id: str
    status: str # "PENDING", "RUNNING", "COMPLETED", "FAILED"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

async def _rewrite_manuscript_task(task_id: str):
    """
    后台任务：使用 LLM 重写稿件。
    """
    tasks[task_id]["status"] = "RUNNING"
    tasks[task_id]["progress"] = 0.0 # 重写任务的进度
    
    try:
        # 确保前置任务已完成且有 full_text
        if tasks[task_id]["status"] != "COMPLETED" or "full_text" not in tasks[task_id]["result"]:
            raise HTTPException(status_code=400, detail="Previous video processing task not completed or full_text not available.")
        
        original_text = tasks[task_id]["result"]["full_text"]
        if not original_text:
            raise HTTPException(status_code=400, detail="No full_text found for rewriting.")

        # 初始化 LLM 管理器
        llm_manager = LlmManager(config)
        llm_provider = llm_manager.get_provider()
        if not llm_provider:
            raise Exception("LLM provider not initialized. Check config.yaml.")

        log.info(f"Rewriting manuscript for task {task_id} using LLM...")
        
        # 构建重写提示词
        prompt = f"请将以下文本进行润色和重写，使其更具吸引力、流畅性，并保持原意。请直接返回重写后的文本，不要包含任何额外说明或标题：\n\n{original_text}"
        
        # 调用 LLM 进行重写
        # 假设 llm_provider.generate_text 是一个异步方法
        rewritten_text = await llm_provider.generate_text(prompt)
        
        if not rewritten_text:
            raise Exception("LLM failed to generate rewritten text.")

        tasks[task_id]["result"]["rewritten_text"] = rewritten_text
        tasks[task_id]["status"] = "COMPLETED"
        tasks[task_id]["progress"] = 1.0
        log.success(f"Manuscript rewriting for task {task_id} completed successfully.")

    except Exception as e:
        error_message = f"Manuscript rewriting failed: {str(e)}"
        log.error(f"Background manuscript rewriting task '{task_id}' failed: {error_message}", exc_info=True)
        tasks[task_id]["status"] = "FAILED"
        tasks[task_id]["error"] = error_message
        tasks[task_id]["progress"] = 1.0


@router.post("/rewrite_manuscript", response_model=RewriteManuscriptResponse, dependencies=[Depends(verify_token)])
async def rewrite_manuscript(request: RewriteManuscriptRequest, background_tasks: BackgroundTasks):
    """
    使用 LLM 重写指定任务ID的视频稿件。
    """
    task_id = request.task_id
    
    # 检查任务是否存在且已完成视频处理
    if task_id not in tasks or tasks[task_id]["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail=f"Task '{task_id}' not found or not completed video processing.")
    
    # 检查是否已经有重写任务在进行或已完成
    if "rewritten_text" in tasks[task_id]["result"] and tasks[task_id]["status"] == "COMPLETED":
        return RewriteManuscriptResponse(
            task_id=task_id, 
            status="COMPLETED", 
            result={"rewritten_text": tasks[task_id]["result"]["rewritten_text"]}
        )
    
    # 更新任务状态为重写中
    tasks[task_id]["status"] = "REWRITING_PENDING" # 新增一个状态
    tasks[task_id]["progress"] = 0.0
    
    background_tasks.add_task(
        _rewrite_manuscript_task, 
        task_id
    )
    
    return RewriteManuscriptResponse(task_id=task_id, status="REWRITING_PENDING", progress=0.0)
