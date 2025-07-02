import ollama
import json
from src.logger import log
from src.color_utils import (
    print_colored,
    print_error,
    print_warning,
    print_success,
    print_info,
)
def _parse_llm_json_response(raw_text: str) -> list | None:
    """
    从LLM的原始输出中稳健地解析出JSON数组。
    它会找到第一个'['和最后一个']'来提取JSON部分，以应对模型返回多余文本的情况。
    """
    try:
        # 找到JSON数组的开始和结束位置
        start_index = raw_text.find('[')
        end_index = raw_text.rfind(']')
        
        if start_index == -1 or end_index == -1 or start_index > end_index:
            log.error("LLM响应中未找到有效的JSON数组。")
            log.debug("原始响应: %r", raw_text)
            return None
            
        json_str = raw_text[start_index : end_index + 1]
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        log.error("解析LLM的JSON响应失败: %s", e, exc_info=True)
        log.debug("原始响应: %r", raw_text)
        return None

def group_segments_into_scenes(segments: list, config: dict) -> list:
    """
    使用Ollama大模型将字幕片段(segments)按语义合并成场景(scenes)。

    :param segments: 从SRT文件解析出的片段列表。
    :param config: 包含Ollama配置的字典。
    :return: 场景列表，每个场景是一个包含时长、文本和待填充关键词的字典。
    """
    ollama_config = config.get('ollama', {})
    if not ollama_config.get('model'):
        log.error("Ollama未在config.yaml中配置。无法进行语义场景分割。")
        return []

    print_info("正在使用Ollama (%s) 进行语义场景分割...", ollama_config['model'])
    
    # 1. 准备带行号的完整文稿，让LLM能够引用
    numbered_transcript = ""
    for i, segment in enumerate(segments):
        # 使用1-based的行号，这更符合自然语言的习惯
        numbered_transcript += f"{i + 1}: {segment['text']}\n"

    # 2. 设计专业的指令(Prompt)
    prompt = f"""
You are an expert video editor and script analyst. Your primary goal is to group lines from a transcript into meaningful, narrative scenes. A scene should cover a complete event, thought, or topic before moving to the next. Avoid creating very short scenes of only one or two lines unless they represent a clear, standalone transition. Strive to group related sentences together to tell a small, complete part of the story.

Here is the numbered transcript:
---
{numbered_transcript.strip()}
---

Analyze the transcript and identify the scene breaks. For each scene, provide the start and end line numbers.

**JSON Output Format Example:**
[
  {{
    "start_line": 1,
    "end_line": 3
  }},
  {{
    "start_line": 4,
    "end_line": 6
  }}
]

**IMPORTANT INSTRUCTIONS:**
- Your entire response MUST be ONLY the valid JSON array. Do not add any introductory text, explanations, or markdown formatting.
- The line numbers in your output must correspond to the numbers in the provided transcript.
- The line number ranges must be continuous and cover the entire transcript from line 1 to line {len(segments)}.
"""

    # 3. 调用Ollama并解析返回的场景边界
    try:
        client = ollama.Client(host=ollama_config.get('host', 'http://localhost:11434'))
        response = client.generate(model=ollama_config['model'], prompt=prompt)
        scene_boundaries = _parse_llm_json_response(response['response'])
        if not scene_boundaries:
            log.error("无法从LLM响应中解析场景边界。")
            return []
    except Exception as e:
        log.error("调用Ollama API失败。", exc_info=True)
        return []

    # 4. 根据LLM返回的行号，重新构建场景
    scenes = []
    for boundary in scene_boundaries:
        try:
            # 将1-based的行号转为0-based的索引
            start_index = int(boundary['start_line']) - 1
            end_index = int(boundary['end_line']) - 1

            if not (0 <= start_index < len(segments) and 0 <= end_index < len(segments) and start_index <= end_index):
                log.warning("LLM返回了无效的行号范围: %s。跳过此场景。", boundary)
                continue

            scene_segments = segments[start_index : end_index + 1]
            if not scene_segments:
                continue

            scene_start_time = scene_segments[0]['start']
            scene_end_time = scene_segments[-1]['end']
            
            scenes.append({
                "scene_start": scene_start_time,
                "scene_end": scene_end_time,
                "duration": scene_end_time - scene_start_time,
                "text": "".join(s['text'] for s in scene_segments),
                "keywords": [] # This will be populated in the next step
            })
        except (KeyError, ValueError, TypeError) as e:
            log.warning("解析LLM返回的场景边界 '%s' 时出错: %s。跳过此场景。", boundary, e, exc_info=True)
            continue
            
    print_info("字幕已通过LLM语义合并为 %d 个场景。", len(scenes))
    return scenes
