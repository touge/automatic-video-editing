import json
from typing import Optional
from src.logger import log
from src.providers.llm import LlmManager

import re

def _parse_llm_json_response(raw_text: str, prompt: str = None) -> dict | None:
    """
    Robustly parses a JSON object from the LLM's raw output.
    It handles markdown code blocks and conversational text around the JSON.
    """
    # 1. 优先查找 ```json ... ``` 代码块
    match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_text)
    if match:
        json_str = match.group(1)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            log.error("Failed to parse JSON from markdown block: %s", e)
            log.warning("--- RAW LLM RESPONSE THAT CAUSED THE ERROR ---\n%r\n---------------------------------", raw_text)
            if prompt:
                log.warning(f"--- PROMPT THAT CAUSED THE ERROR ---\n{prompt}\n---------------------------------")
            return None

    # 2. 如果没有代码块，则查找第一个 '{' 或 '['，并从那里开始解码
    # 这种方法对于 JSON 前后的对话性文本更健壮
    start_brace = raw_text.find('{')
    start_bracket = raw_text.find('[')

    start_index = -1
    if start_brace != -1 and start_bracket != -1:
        start_index = min(start_brace, start_bracket)
    elif start_brace != -1:
        start_index = start_brace
    elif start_bracket != -1:
        start_index = start_bracket

    if start_index != -1:
        try:
            # 使用 raw_decode 从字符串中解析第一个有效的 JSON 对象
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(raw_text[start_index:])
            return obj
        except json.JSONDecodeError as e:
            log.error("Failed to parse LLM JSON response: %s", e)
            log.warning("--- RAW LLM RESPONSE THAT CAUSED THE ERROR ---\n%r\n---------------------------------", raw_text)
            if prompt:
                log.warning(f"--- PROMPT THAT CAUSED THE ERROR ---\n{prompt}\n---------------------------------")
            return None

    log.warning("No valid JSON object found in LLM response. Response: %r", raw_text[:200] + "...")
    return None

class KeywordGenerator:
    def __init__(self, config: dict, style: Optional[str] = None):
        self.config = config
        self.llm_manager = LlmManager(config)
        if not self.llm_manager.get_provider():
            raise ValueError("LLM provider is not available for KeywordGenerator.")
        
        log.info(f"KeywordGenerator initialized with style: '{style}'.")
        
        self.prompt_template = self._load_prompt_template(style)

    def _load_prompt_template(self, style: Optional[str]) -> str:
        """根据指定的风格选择提示词模板的路径。"""
        prompt_config = self.config.get('prompts', {}).get('scene_keywords', {})
        if not prompt_config:
            raise ValueError("Prompt config 'prompts.scene_keywords' not found in config.yaml")

        style_key = style if style and style in prompt_config else 'default'
        
        prompt_path = prompt_config.get(style_key)
        if not prompt_path:
            raise ValueError(f"Prompt path for style '{style_key}' not found in config.")

        log.info(f"Selected keyword prompt for style '{style_key}'")
        return prompt_path


    def generate_for_scenes(self, scenes: list) -> list:
        min_duration = self.config.get("composition_settings.min_duration", 3)
        for scene in scenes:
            try:
                # 构造传递给提供者的参数，提供者将负责读取和格式化模板
                generation_params = {
                    "min_duration": min_duration,
                    "scene_text": scene["text"],
                    "duration": scene["duration"]
                }

                # self.prompt_template 现在是一个文件路径
                # 将路径和格式化参数都传递给 LLM 管理器
                response_text = self.llm_manager.generate_with_failover(
                    self.prompt_template, 
                    **generation_params
                )

                # 解析 LLM 输出的 JSON 文本，转为结构化格式
                prompt_context_for_logging = f"Template: {self.prompt_template}, Params: {generation_params}"
                parsed_data = _parse_llm_json_response(response_text, prompt=prompt_context_for_logging)

                # 如果生成结果合法，并且包含 'scenes' 字段
                if parsed_data and isinstance(parsed_data, dict) and 'scenes' in parsed_data:
                    sub_scenes = parsed_data.get('scenes', [])
                    scene['scenes'] = sub_scenes
                else:
                    # 如果解析失败，则设置为空列表
                    scene['scenes'] = []
            
            except Exception as e:
                # 捕获异常，打印错误日志（截取前30字符避免过长）
                log.error(
                    f"Failed to generate keywords for scene: \"{scene['text'][:30]}...\"。",
                    exc_info=True
                )
                scene['scenes'] = []

        # 返回处理后的完整场景列表
        return scenes
