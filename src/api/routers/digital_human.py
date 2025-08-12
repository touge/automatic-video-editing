# -*- coding: utf-8 -*-
"""
本脚本负责处理所有与数字人视频相关的功能，包括：
1.  生成：调用第三方服务，根据音频生成带绿幕的原始数字人视频。
2.  处理：对原始视频进行绿幕抠图，并替换为指定的背景。
3.  合成：将处理好的视频，根据精确的时间和位置信息，叠加到主视频上。

所有接口都设计为异步后台任务，以避免阻塞服务器。
"""

import os
import sys
import json
import time
import asyncio
import requests
from fastapi import APIRouter, Depends, HTTPException, Form, Request, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Union
from urllib.parse import urlparse

# --- 项目根路径设置 ---
# 将项目根目录添加到Python的模块搜索路径中，以确保所有模块都能被正确导入。
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- 内部模块导入 ---
from src.config_loader import config
from src.core.task_manager import TaskManager
from src.providers.digital_human import get_digital_human_provider, DigitalHumanProvider
from src.core.service_controller import ServiceController
from src.logic.digital_human_compositor import DigitalHumanCompositor
from src.core.video_compositor import VideoCompositor
from src.api.security import verify_token
from src.logger import log
from starlette.concurrency import run_in_threadpool
from src.utils import get_relative_url, to_slash_path

# --- FastAPI路由设置 ---
# 创建一个FastAPI路由实例，所有本文件中的API都将注册到这个路由上。
router = APIRouter(
    prefix="/tasks",  # 所有API路径都以 /tasks 开头
    tags=["Digital Human & Composition"],  # 在API文档中显示的标签
    dependencies=[Depends(verify_token)]  # 为所有API应用安全验证依赖
)

# --- Pydantic数据模型定义 ---
# 使用Pydantic模型来定义API的请求体结构，可以实现自动的数据校验和文档生成。

class Position(BaseModel):
    """定义坐标位置的模型"""
    x: Union[int, str]  # x坐标，可以是像素值或FFmpeg表达式
    y: Union[int, str]  # y坐标

class ClipParams(BaseModel):
    """定义视频裁剪参数的模型"""
    start: float = 0.0  # 裁剪开始时间（秒）
    duration: Optional[float] = None  # 裁剪持续时间（秒）

class SegmentSpec(BaseModel):
    """定义单个视频片段合成规格的模型"""
    start_time: Optional[float] = None  # 在主视频时间线上的开始时间
    clip_params: Optional[ClipParams] = None  # 对该片段自身的裁剪
    volume: Optional[float] = None  # 音量
    size: Optional[str] = None  # 尺寸，如 "1920x1080"
    position: Optional[Position] = None  # 位置

class CompositeDigitalHumanRequest(BaseModel):
    """定义最终合成接口的请求体模型"""
    segments: Optional[List[SegmentSpec]] = None  # 多个视频片段的规格列表
    main_clip_params: Optional[ClipParams] = None  # 对主视频的裁剪
    base_video_volume: float = 1.0  # 主视频音量
    output_filename: str = "final_video_composited.mp4"  # 输出文件名

# --- 任务一：生成数字人视频 ---
def _download_and_save_file(url: str, save_path: str):
    """一个辅助函数，用于从URL下载文件并保存到本地。"""
    proxies = {"http": None, "https": None}  # 禁用代理，确保能访问本地或局域网服务
    with requests.get(url, stream=True, proxies=proxies) as r:
        r.raise_for_status()  # 如果HTTP请求返回错误状态码，则抛出异常
        with open(save_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):  # 分块写入，避免消耗过多内存
                f.write(chunk)
    log.info(f"File downloaded from {url} to {save_path}")

async def _wait_for_file_stable(file_path: str, timeout: int = 60, check_interval: int = 1, stable_checks: int = 3):
    """
    等待一个文件存在，并且其大小在连续多次检查中保持稳定。
    这是一个更健壮的方法，用于确保文件已完全写入。
    """
    start_time = time.time()
    last_size = -1
    stable_count = 0

    log.info(f"Waiting for file '{file_path}' to become stable...")
    while time.time() - start_time < timeout:
        # 首先检查文件是否存在
        if not os.path.exists(file_path):
            await asyncio.sleep(check_interval)
            continue  # 如果文件不存在，继续等待

        # 获取当前文件大小
        current_size = os.path.getsize(file_path)
        
        # 比较文件大小
        if current_size == last_size and current_size > 0:
            # 如果大小与上次相同且不为0，增加稳定计数
            stable_count += 1
        else:
            # 如果大小发生变化或文件为空，重置计数器
            stable_count = 0

        # 更新上一次的大小
        last_size = current_size
        
        # 检查是否达到连续稳定的次数要求
        if stable_count >= stable_checks:
            log.info(f"File '{file_path}' is stable with size {current_size} bytes after {stable_checks} consecutive checks.")
            return True
        
        # 等待下一个检查周期
        await asyncio.sleep(check_interval)
    
    # 如果超时，则抛出异常
    raise TimeoutError(f"File '{file_path}' did not become stable within {timeout} seconds.")

async def _generate_digital_human_task(task_id: str, character_name: str, segments_json: str, provider: DigitalHumanProvider, http_request: Request):
    """生成数字人视频的后台任务。"""
    # 初始化任务管理器和服务控制器
    task_manager = TaskManager(task_id)
    service_controller = ServiceController()
    heygem_service_name = "HeygemAPI"  # 依赖的服务名称
    step_name = "digital_human_generation"  # 当前步骤的名称

    try:
        # 1. 更新任务状态为“正在运行”
        task_manager.update_task_status(TaskManager.STATUS_RUNNING, step=step_name, details={"message": "Starting digital human video generation."})
        
        # 2. 检查并等待音频文件稳定
        audio_path = task_manager.get_file_path('final_audio')
        await _wait_for_file_stable(audio_path)

        # 3. 启动依赖的外部服务
        service_controller.safe_start(heygem_service_name, timeout=300)
        
        # 4. 调用视频生成服务（这是一个耗时操作，放在线程池中运行）
        result = await run_in_threadpool(
            provider.generate_video,
            audio_file_path=audio_path,
            character_name=character_name,
            segments_json=segments_json
        )
        
        # 5. 处理返回结果，下载视频文件
        data = result.get("data", {})
        main_video_url = data.get("url")
        segment_urls = data.get("urls", [])

        if not main_video_url:
            raise ValueError("Could not find main video URL in API response.")

        # 创建用于存放视频的目录
        dh_video_dir = os.path.join(task_manager.task_path, ".videos", "digital_human")
        os.makedirs(dh_video_dir, exist_ok=True)

        # 下载主视频和所有切片视频
        main_video_filename = os.path.basename(urlparse(main_video_url).path)
        main_video_local_path = os.path.join(dh_video_dir, main_video_filename)
        await run_in_threadpool(_download_and_save_file, main_video_url, main_video_local_path)
        
        main_video_relative_url = get_relative_url(main_video_local_path, http_request)
        
        local_segment_urls = []
        local_segment_paths = []
        if segment_urls:
            dh_segment_dir = os.path.join(dh_video_dir, "segments")
            os.makedirs(dh_segment_dir, exist_ok=True)
            for seg_url in segment_urls:
                seg_filename = os.path.basename(urlparse(seg_url).path)
                seg_local_path = os.path.join(dh_segment_dir, seg_filename)
                await run_in_threadpool(_download_and_save_file, seg_url, seg_local_path)
                local_segment_urls.append(get_relative_url(seg_local_path, http_request))
                local_segment_paths.append(seg_local_path)

        # 6. 解析时间片段JSON
        parsed_segments = json.loads(segments_json) if segments_json else []

        # 7. 构建成功信息并更新任务状态
        success_details = {
            "message": "Digital human video and segments generated successfully.",
            "digital_human": {
                "video": {"path": to_slash_path(main_video_local_path), "url": main_video_relative_url},
                "segment_videos": {"paths": [to_slash_path(p) for p in local_segment_paths], "urls": local_segment_urls},
                "segments": parsed_segments
            }
        }
        task_manager.update_task_status(TaskManager.STATUS_SUCCESS, step=step_name, details=success_details)
        log.success(f"Digital human video and segments for task '{task_id}' processed successfully.")

    except Exception as e:
        # 异常处理：记录错误日志并更新任务状态为“失败”
        error_message = f"Failed to generate digital human video: {str(e)}"
        log.error(f"Task '{task_id}' failed: {error_message}", exc_info=True)
        task_manager.update_task_status(TaskManager.STATUS_FAILED, step=step_name, details={"message": error_message})
    finally:
        # 确保依赖的服务最终被停止
        service_controller.stop(heygem_service_name)
        log.info(f"Service '{heygem_service_name}' stopped.")

# --- 任务二：处理视频切片 ---
async def _process_segments_task(task_id: str, http_request: Request):
    """处理视频切片（绿幕抠图）的后台任务。"""
    task_manager = TaskManager(task_id)
    step_name = "process_digital_human_segments"
    
    try:
        # 1. 更新任务状态为“正在运行”
        task_manager.update_task_status(TaskManager.STATUS_RUNNING, step=step_name, details={"message": "Starting segment processing (chroma key)."})
        
        # 2. 从status.json获取待处理的视频路径
        status = task_manager.get_task_status()
        digital_human_data = status.get("digital_human", {})
        segment_paths = digital_human_data.get("segment_videos", {}).get("paths", [])

        if not segment_paths:
            raise ValueError("No video segments found to process.")

        # 创建用于存放处理后视频的目录
        processed_dir = os.path.join(task_manager.task_path, ".videos", "digital_human", "processed_segments")
        os.makedirs(processed_dir, exist_ok=True)

        # 3. 初始化视频合成器并准备处理结果列表
        compositor = VideoCompositor()
        processed_paths = []
        processed_urls = []

        # 4. 从配置文件读取背景图片路径
        background_path = config.get("composition_settings", {}).get("video_background")
        if not background_path or not os.path.exists(background_path):
            raise ValueError(f"Background image not found at path: {background_path}")

        # 5. 遍历每个视频切片，调用核心处理方法
        for segment_path in segment_paths:
            base_filename, _ = os.path.splitext(os.path.basename(segment_path))
            output_filename = f"{base_filename}.mp4"
            output_path = os.path.join(processed_dir, output_filename)
            
            # 调用 process_short_video 进行抠图和背景替换
            success = await run_in_threadpool(
                compositor.process_short_video,
                input_path=segment_path,
                output_path=output_path,
                background_path=background_path
            )
            # 严格检查执行结果，如果失败则立即终止任务
            if not success:
                raise Exception(f"Failed to process segment: {segment_path}")

            processed_paths.append(output_path)
            processed_urls.append(get_relative_url(output_path, http_request))

        # 6. 安全地更新status.json，追加处理结果
        current_digital_human_data = status.get("digital_human", {})
        current_digital_human_data["processed_segment_videos"] = {
            "paths": [to_slash_path(p) for p in processed_paths],
            "urls": processed_urls
        }
        task_manager.update_task_status(TaskManager.STATUS_SUCCESS, step=step_name, details={"digital_human": current_digital_human_data})
        log.success(f"Chroma key processing completed for task '{task_id}'.")

    except Exception as e:
        # 异常处理
        error_message = f"Failed to process video segments: {str(e)}"
        log.error(f"Task '{task_id}' failed: {error_message}", exc_info=True)
        task_manager.update_task_status(TaskManager.STATUS_FAILED, step=step_name, details={"message": error_message})

# --- 任务三：合成最终视频 ---
async def _composite_task(task_id: str, request_body: Optional[CompositeDigitalHumanRequest], http_request: Request):
    """合成最终视频的后台任务。"""
    task_manager = TaskManager(task_id)
    step_name = "digital_human_composition"
    
    try:
        # 1. 更新任务状态为“正在运行”
        task_manager.update_task_status(TaskManager.STATUS_RUNNING, step=step_name, details={"message": "Digital human composition task has started."})
        
        # 2. 初始化逻辑层的合成器
        compositor = DigitalHumanCompositor(task_id)
        
        # 3. 准备合成参数（处理默认值和用户自定义值）
        main_clip_params_dict = None
        base_video_volume = 1.0
        output_filename = "final_video_composited.mp4"

        status = task_manager.get_task_status()
        video_info = status.get("video_info", {})
        main_video_resolution = video_info.get("resolution", "1920x1080")
        default_volume = 0

        if request_body:
            if request_body.main_clip_params:
                main_clip_params_dict = request_body.main_clip_params.model_dump(exclude_unset=True)
            base_video_volume = getattr(request_body, 'base_video_volume', base_video_volume)
            output_filename = getattr(request_body, 'output_filename', output_filename)

        # 4. 构建最终传递给FFmpeg的规格列表
        specs_as_dicts = []
        if request_body and request_body.segments:
            # 情况一：用户通过请求体提供了自定义规格
            log.info("Using segments from request body.")
            for seg in request_body.segments:
                spec = seg.model_dump(exclude_unset=False)
                # 智能补全缺失的参数
                if spec.get('volume') is None: spec['volume'] = default_volume
                if spec.get('size') is None: spec['size'] = main_video_resolution
                if spec.get('position') is None: spec['position'] = {"x": "(W-w)/2", "y": "(H-h)/2"}
                specs_as_dicts.append(spec)
        else:
            # 情况二：用户未提供，使用status.json中的默认规格
            log.info("Using segments from status.json.")
            digital_human_data = status.get("digital_human", {})
            if not digital_human_data or "segments" not in digital_human_data:
                raise ValueError("Segment data not found in task status.")

            for seg_info in digital_human_data["segments"]:
                start_str, end_str = seg_info.get("start"), seg_info.get("end")
                # 定义一个内部函数来解析时间字符串（支持负数）
                def parse_time(t_str):
                    neg = t_str.startswith('-')
                    parts = t_str.strip('-').split(':')
                    secs = sum(int(p) * 60**i for i, p in enumerate(reversed(parts)))
                    return -secs if neg else secs
                start_secs, end_secs = parse_time(start_str), parse_time(end_str)
                duration = abs(end_secs - start_secs)
                specs_as_dicts.append({
                    "start_time": start_secs,
                    "clip_params": {"start": 0, "duration": duration},
                    "volume": default_volume,
                    "size": main_video_resolution,
                    "position": {"x": "(W-w)/2", "y": "(H-h)/2"}
                })
        
        # 5. 调用逻辑层执行合成（这是一个耗时操作）
        final_video_path = await run_in_threadpool(
            compositor.run,
            composition_specs=specs_as_dicts,
            output_filename=output_filename,
            main_clip_params=main_clip_params_dict,
            base_video_volume=base_video_volume
        )
        
        # 6. 任务成功，更新状态并记录最终文件路径
        video_url = get_relative_url(final_video_path, http_request)
        task_manager.update_task_status(TaskManager.STATUS_SUCCESS, step=step_name, details={
            "message": "Composition completed successfully.",
            "composited_video_url": video_url,
            "composited_video_path": to_slash_path(final_video_path)
        })
        log.success(f"Composition task '{task_id}' completed successfully.")
        
    except Exception as e:
        # 异常处理
        error_message = f"Composition failed: {str(e)}"
        log.error(f"Task '{task_id}' failed: {error_message}", exc_info=True)
        task_manager.update_task_status(TaskManager.STATUS_FAILED, step=step_name, details={"message": error_message})

# --- API接口定义 ---
@router.post("/{task_id}/digital-human/generate", summary="1. Generate Digital Human Video (Async)")
async def generate_digital_human_video(
    task_id: str,
    background_tasks: BackgroundTasks,
    http_request: Request,
    character_name: str = Form("44s-医生"),
    segments_json: Optional[str] = Form('[{"start":"00:00:00","end":"00:00:45"},{"start":"-00:00:45","end":"-00:00:00"}]'),
    provider: DigitalHumanProvider = Depends(get_digital_human_provider)
):
    """接收请求，将数字人视频生成任务添加到后台执行。"""
    task_manager = TaskManager(task_id)
    if not os.path.exists(task_manager.task_path):
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    
    # 将真正的任务逻辑添加到后台任务队列
    background_tasks.add_task(_generate_digital_human_task, task_id, character_name, segments_json, provider, http_request)
    
    # 立即返回响应，告知用户任务已提交
    message = "Digital human generation task submitted."
    task_manager.update_task_status(
        TaskManager.STATUS_PENDING,
        step="digital_human_generation",
        details={"message": message}
    )
    return {"task_id": task_id, "status": TaskManager.STATUS_PENDING, "message": message}

@router.post("/{task_id}/digital-human/process", summary="2. Process Digital Human Segments (Async)")
async def process_digital_human_segments(task_id: str, background_tasks: BackgroundTasks, http_request: Request):
    """接收请求，将视频切片处理（抠图）任务添加到后台执行。"""
    task_manager = TaskManager(task_id)
    status = task_manager.get_task_status()
    # 前置条件检查：必须先生成了原始视频切片
    if not status.get("digital_human", {}).get("segment_videos"):
        raise HTTPException(status_code=404, detail="Raw digital human segments not found. Please run the generation step first.")

    background_tasks.add_task(_process_segments_task, task_id, http_request)
    
    message = "Segment processing task submitted."
    task_manager.update_task_status(
        TaskManager.STATUS_PENDING,
        step="process_digital_human_segments",
        details={"message": message}
    )
    return {"task_id": task_id, "status": TaskManager.STATUS_PENDING, "message": message}

@router.post("/{task_id}/digital-human/composite", summary="3. Composite Final Video (Async)")
async def composite_digital_human(task_id: str, background_tasks: BackgroundTasks, http_request: Request, body: Optional[CompositeDigitalHumanRequest] = None):
    """接收请求，将最终视频合成任务添加到后台执行。"""
    task_manager = TaskManager(task_id)
    status = task_manager.get_task_status()
    # 前置条件检查：必须存在数字人相关数据
    if not status.get("digital_human"):
        raise HTTPException(status_code=404, detail="Digital human data not found. Please run generation and processing steps first.")

    background_tasks.add_task(_composite_task, task_id, body, http_request)
    
    message = "Composition task submitted."
    task_manager.update_task_status(
        TaskManager.STATUS_PENDING,
        step="digital_human_composition",
        details={"message": message}
    )
    return {"task_id": task_id, "status": TaskManager.STATUS_PENDING, "message": message}
