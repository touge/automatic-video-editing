import json
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
    def __init__(self, config: dict):
        self.config = config
        self.llm_manager = LlmManager(config)
        if not self.llm_manager.get_provider():
            raise ValueError("LLM provider is not available for KeywordGenerator.")
        
        log.info("KeywordGenerator initialized.")
        
        self.prompt_template = config.get('prompts', {}).get('keyword_generator')
        if not self.prompt_template:
            raise ValueError("Keyword generator prompt 'prompts.keyword_generator' not found in config.yaml")


    def generate_for_scenes(self, scenes: list) -> list:
        # 对每条视频描述文本进行 prompt 注入 → 请求模型 → 解析结果 → 校验时长 → 写入结构化结果。
        # 遍历所有输入的场景（每个场景包含 text 和 duration）
        min_duration = self.config.get("composition_settings.min_sub_scene_duration", 3)
        for scene in scenes:
            try:
                # 🔨 构造提示词：将 scene 文本和时长嵌入模板
                prompt = self.prompt_template.format(
                    min_duration=min_duration,
                    scene_text=scene["text"], 
                    duration=scene["duration"]
                )

                # print(f"prompt:{prompt}")

                # 🎯 向大模型请求生成结果（带 failover 容错处理）
                response_text = self.llm_manager.generate_with_failover(prompt)
                # print(f"response_text:{response_text}")

                # 📤 解析 LLM 输出的 JSON 文本，转为结构化格式
                parsed_data = _parse_llm_json_response(response_text, prompt=prompt)

                # ✅ 如果生成结果合法，并且包含 'scenes' 字段
                if parsed_data and isinstance(parsed_data, dict) and 'scenes' in parsed_data:
                    sub_scenes = parsed_data.get('scenes', [])
                    scene['scenes'] = sub_scenes
                else:
                    # ❌ 如果解析失败，则设置为空列表
                    scene['scenes'] = []
            
            except Exception as e:
                # 🚨 捕获异常，打印错误日志（截取前30字符避免过长）
                log.error(
                    f"Failed to generate keywords for scene: \"{scene['text'][:30]}...\"。",
                    exc_info=True
                )
                scene['scenes'] = []

        # 🔚 返回处理后的完整场景列表
        return scenes
