import os
import json
from typing import Optional
from src.logger import log
from src.providers.llm import LlmManager

import re

def _parse_llm_json_response(raw_text: str, prompt: str = None) -> dict | None:
    """
    Robustly parses a JSON object from the LLM's raw output.
    It handles markdown code blocks, conversational text, and <think> blocks.
    """
    # --- 调试代码：打印完整的输入和输出 ---
    print("\n" + "="*30 + " LLM DEBUG START " + "="*30)
    if prompt:
        print("\n--- PROMPT SENT TO LLM ---\n")
        print(prompt)
    print("\n--- RAW RESPONSE FROM LLM ---\n")
    print(raw_text)
    print("\n" + "="*31 + " LLM DEBUG END " + "="*31 + "\n")
    # --- 调试代码结束 ---

    # 1. 移除 <think>...</think> 块
    cleaned_text = re.sub(r'<think>[\s\S]*?</think>', '', raw_text).strip()

    # 2. 优先查找 ```json ... ``` 代码块
    match = re.search(r'```json\s*([\s\S]*?)\s*```', cleaned_text)
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

    # 3. 如果没有代码块，则查找第一个 '{' 或 '['，并从那里开始解码
    # 这种方法对于 JSON 前后的对话性文本更健壮
    start_brace = cleaned_text.find('{')
    start_bracket = cleaned_text.find('[')

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
            obj, _ = decoder.raw_decode(cleaned_text[start_index:])
            return obj
        except json.JSONDecodeError as e:
            log.error("Failed to parse LLM JSON response: %s", e)
            log.warning("--- RAW LLM RESPONSE THAT CAUSED THE ERROR ---\n%r\n---------------------------------", cleaned_text)
            if prompt:
                log.warning(f"--- PROMPT THAT CAUSED THE ERROR ---\n{prompt}\n---------------------------------")
            return None

    log.warning("No valid JSON object found in LLM response. Response: %r", cleaned_text[:200] + "...")
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
        """根据指定的风格加载提示词模板，可以是路径也可以是内容。"""
        prompt_config = self.config.get('prompts', {}).get('scene_keywords', {})
        if not prompt_config:
            raise ValueError("Prompt config 'prompts.scene_keywords' not found in config.yaml")

        style_key = style if style and style in prompt_config else 'default'
        
        prompt_path_or_content = prompt_config.get(style_key)
        if not prompt_path_or_content:
            raise ValueError(f"Prompt for style '{style_key}' not found in config.")

        log.info(f"Loading keyword prompt for style '{style_key}'")

        # 检查值是否是一个存在的文件路径
        if isinstance(prompt_path_or_content, str) and os.path.exists(prompt_path_or_content):
            try:
                with open(prompt_path_or_content, 'r', encoding='utf-8') as f:
                    prompt_content = f.read()
                log.info(f"Loaded keyword prompt from file: {prompt_path_or_content}")
                return prompt_content
            except Exception as e:
                raise IOError(f"Error reading keyword prompt file {prompt_path_or_content}: {e}")
        else:
            # 如果不是有效路径，则假定它本身就是提示内容
            log.info("Using keyword prompt directly from config content.")
            return prompt_path_or_content


    def generate_for_scenes(self, scenes: list) -> list:
        min_duration = self.config.get("composition_settings.min_duration", 3)
        for scene in scenes:
            try:
                # 构造用于格式化提示词的完整参数
                generation_params = {
                    "min_duration": min_duration,
                    "scene_text": scene["text"],
                    "duration": scene["duration"],
                    # 为模板中所有可能的占位符提供默认值，以防 KeyError
                    "emotion_tags": "N/A",
                    "camera_tags": "N/A",
                    "action_tags": "N/A",
                    "scene_tags": "N/A",
                    "health_tags": "N/A"
                }

                # 在调用 LLM 之前，先将提示词模板完整格式化
                final_prompt = self.prompt_template.format(**generation_params)

                # 仅将最终的、已格式化的提示词传递给 LLM 管理器
                # 这样既能确保提示词内容正确，又能避免将无效参数传递给底层 API
                response_text = self.llm_manager.generate_with_failover(
                    prompt=final_prompt
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
