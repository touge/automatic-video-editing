import asyncio
from typing import Dict, Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from src.config_loader import config
from src.api.security import verify_token
from src.providers.llm import LlmManager
from src.logger import log
from src.api.routers.yt.rewrite_task_manager import RewriteTaskManager

router = APIRouter()

class RewriteManuscriptRequest(BaseModel):
    task_id: str

class RewriteManuscriptResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

async def _rewrite_manuscript_task(task_id: str):
    """
    后台任务：使用 LLM 重写稿件。
    使用 RewriteTaskManager 来管理状态。
    """
    task_manager = RewriteTaskManager(task_id=task_id)
    
    try:
        # 1. 更新状态为运行中
        task_manager.update_task_status(status=task_manager.STATUS_RUNNING, step="rewriting_manuscript")

        # 2. 从 manuscript.txt 文件加载原始文本
        manuscript_path = f"tasks/{task_id}/manuscript.txt"
        try:
            with open(manuscript_path, "r", encoding="utf-8") as f:
                original_text = f.read()
        except FileNotFoundError:
            raise Exception(f"Manuscript file not found at {manuscript_path}.")

        if not original_text:
            raise Exception("Manuscript file is empty.")

        # 3. 根据配置准备 LLM
        copywriting_config = config.get('copywriting_generation', {})
        provider_override = copywriting_config.get('llm_provider')
        if provider_override:
            log.info(f"Overriding LLM provider to '{provider_override}' for copywriting task.")
            config.set('llm_providers.use', provider_override)
        
        llm_manager = LlmManager(config)
        llm_provider = llm_manager.get_provider()
        if not llm_provider:
            raise Exception("LLM provider not initialized. Check config.yaml.")

        # 4. 加载 Prompt
        rewrite_prompt_path = config.get_raw_value('copywriting_generation.rewrite_prompt')
        if not rewrite_prompt_path:
            raise Exception("Rewrite prompt path not found in config.")

        with open(rewrite_prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
        
        prompt = prompt_template.replace("{original_text}", original_text)
        
        # 5. 调用 LLM 重写
        log.info(f"Rewriting manuscript for task {task_id} using LLM...")
        log.info(f"prompt:\n{prompt}")
        # prompt= "地球上真的有外星人吗？"
        rewritten_text = await run_in_threadpool(llm_provider.generate, prompt)
        
        if not rewritten_text:
            raise Exception("LLM failed to generate rewritten text.")

        # 6. 更新状态为成功
        task_manager.update_task_status(
            status=task_manager.STATUS_SUCCESS,
            step="rewriting_completed",
            details={"result": {"rewritten_text": rewritten_text}}
        )
        log.success(f"Manuscript rewriting for task {task_id} completed successfully.")

    except Exception as e:
        error_message = f"Manuscript rewriting failed: {str(e)}"
        log.error(f"Background manuscript rewriting task '{task_id}' failed: {error_message}", exc_info=True)
        # 更新状态为失败
        task_manager.update_task_status(
            status=task_manager.STATUS_FAILED,
            step="rewriting_failed",
            details={"error": error_message}
        )

@router.post("/rewrite_manuscript", response_model=RewriteManuscriptResponse, dependencies=[Depends(verify_token)])
async def rewrite_manuscript(request: RewriteManuscriptRequest, background_tasks: BackgroundTasks):
    """
    使用 LLM 重写指定任务ID的视频稿件。
    """
    task_id = request.task_id
    task_manager = RewriteTaskManager(task_id=task_id)
    
    # 1. 获取任务状态
    task_info = task_manager.get_task_status()
    status = task_info.get("status")

    # 2. 检查任务是否处于可以重写的状态
    # 初始任务必须完成，或者重写任务失败了，才允许再次发起
    # if status not in [task_manager.STATUS_SUCCESS, task_manager.STATUS_FAILED]:
    #     raise HTTPException(
    #         status_code=400, 
    #         detail=f"Task '{task_id}' is not in a valid state for rewriting. Current status: '{status}'."
    #     )

    # 3. 检查稿件 URL 是否存在
    # if "manuscript_url" not in task_info.get("result", {}):
    #     raise HTTPException(
    #         status_code=400, 
    #         detail=f"Task '{task_id}' is missing 'manuscript_url' in its result."
    #     )

    # 4. 如果任务正在运行，则直接返回状态
    if status == task_manager.STATUS_RUNNING:
        return RewriteManuscriptResponse(task_id=task_id, status=status)

    # 5. 添加后台任务
    background_tasks.add_task(_rewrite_manuscript_task, task_id)
    
    # 6. 返回 PENDING 状态
    return RewriteManuscriptResponse(task_id=task_id, status=task_manager.STATUS_PENDING)
