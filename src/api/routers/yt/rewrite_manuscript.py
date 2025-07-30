import asyncio
from typing import Dict, Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool # 导入 run_in_threadpool

from src.config_loader import config
from src.api.security import verify_token
from src.api.routers.yt.shared_data import tasks, save_task_status, load_task_status # 导入共享的 tasks 字典和 save/load 函数
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
    save_task_status(task_id) # 保存初始状态
    
    try:
        # 移除内部的前置检查，因为 API 调度时已确保条件满足
        original_text = tasks[task_id]["result"]["full_text"] # 直接访问 full_text
        if not original_text:
            raise Exception("No full_text found for rewriting in task result.") # 改为 Exception，因为 HTTPException 不应在后台任务中直接抛出

        # 初始化 LLM 管理器
        llm_manager = LlmManager(config)
        llm_provider = llm_manager.get_provider()
        if not llm_provider:
            raise Exception("LLM provider not initialized. Check config.yaml.")

        log.info(f"Rewriting manuscript for task {task_id} using LLM...")
        
        # 从 config.yaml 加载重写提示词
        # 根据用户反馈，直接使用 gemini_rewrite 路径
        rewrite_prompt_path = config.get('prompts.gemini_rewrite')
        if not rewrite_prompt_path:
            raise Exception("Gemini rewrite prompt path not found in config.yaml.")
        
        try:
            with open(rewrite_prompt_path, "r", encoding="utf-8") as f:
                prompt_template = f.read()
        except FileNotFoundError:
            raise Exception(f"Gemini rewrite prompt file not found at {rewrite_prompt_path}.")
        
        # 构建重写提示词
        prompt = prompt_template.replace("{original_text}", original_text) # 假设模板中包含 {original_text} 占位符
        
        # 调用 LLM 进行重写，将其放入线程池以避免阻塞
        rewritten_text = await run_in_threadpool(llm_provider.generate, prompt)
        
        if not rewritten_text:
            raise Exception("LLM failed to generate rewritten text.")

        tasks[task_id]["result"]["rewritten_text"] = rewritten_text
        tasks[task_id]["status"] = "COMPLETED"
        tasks[task_id]["progress"] = 1.0
        log.success(f"Manuscript rewriting for task {task_id} completed successfully.")
        save_task_status(task_id) # 保存完成状态

    except Exception as e:
        error_message = f"Manuscript rewriting failed: {str(e)}"
        log.error(f"Background manuscript rewriting task '{task_id}' failed: {error_message}", exc_info=True)
        tasks[task_id]["status"] = "FAILED"
        tasks[task_id]["error"] = error_message
        tasks[task_id]["progress"] = 1.0
        save_task_status(task_id) # 保存失败状态


@router.post("/rewrite_manuscript", response_model=RewriteManuscriptResponse, dependencies=[Depends(verify_token)])
async def rewrite_manuscript(request: RewriteManuscriptRequest, background_tasks: BackgroundTasks):
    """
    使用 LLM 重写指定任务ID的视频稿件。
    """
    task_id = request.task_id
    
    # 尝试从内存或文件加载任务状态
    task_info = tasks.get(task_id)
    if not task_info:
        task_info = load_task_status(task_id)
        if task_info:
            tasks[task_id] = task_info # 加载到内存中
    
    # 检查任务是否存在且已完成视频处理
    if not task_info or task_info["status"] != "COMPLETED" or "full_text" not in task_info["result"]:
        raise HTTPException(status_code=400, detail=f"Task '{task_id}' not found, not completed video processing, or full_text not available.")
    
    # 检查是否已经有重写任务在进行或已完成
    if "rewritten_text" in task_info["result"] and task_info["status"] == "COMPLETED":
        return RewriteManuscriptResponse(
            task_id=task_id, 
            status="COMPLETED", 
            result={"rewritten_text": task_info["result"]["rewritten_text"]}
        )
    
    # 更新任务状态为重写中
    tasks[task_id]["status"] = "REWRITING_PENDING" # 新增一个状态
    tasks[task_id]["progress"] = 0.0
    
    background_tasks.add_task(
        _rewrite_manuscript_task, 
        task_id
    )
    
    return RewriteManuscriptResponse(task_id=task_id, status="REWRITING_PENDING", progress=0.0)
