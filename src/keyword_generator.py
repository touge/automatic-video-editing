import json
from src.logger import log
from src.providers.llm import LlmManager

import re

def _parse_llm_json_response(raw_text: str) -> dict | None:
    """
    Robustly parses a JSON object from the LLM's raw output.
    It first looks for a ```json ... ``` code block.
    If not found, it falls back to finding the first '{' and last '}'.
    """
    json_str = ""
    # 1. 优先查找 ```json ... ``` 代码块
    match = re.search(r'```json\s*([\s\S]*?)\s*```', raw_text)
    if match:
        json_str = match.group(1)
    else:
        # 2. 如果没有代码块，回退到查找第一个和最后一个大括号
        try:
            start_index = raw_text.find('{')
            end_index = raw_text.rfind('}')
            
            if start_index != -1 and end_index != -1 and start_index < end_index:
                json_str = raw_text[start_index : end_index + 1]
            else:
                 log.warning("No valid JSON object found in LLM response. Response: %r", raw_text[:200] + "...")
                 return None
        except Exception:
             log.warning("Could not find JSON object in raw text. Response: %r", raw_text[:200] + "...")
             return None

    # 3. 尝试解析提取出的字符串
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        log.error("Failed to parse LLM JSON response: %s", e)
        log.debug("Extracted JSON string for parsing: %r", json_str)
        log.debug("Original raw response from LLM: %r", raw_text)
        return None

class KeywordGenerator:
    def __init__(self, config: dict):
        self.llm_manager = LlmManager(config)
        if not self.llm_manager.ordered_providers:
            raise ValueError("No LLM providers are available for KeywordGenerator. Please check your config.yaml.")
        
        log.info("KeywordGenerator initialized.")
        
        self.prompt_template = config.get('prompts', {}).get('keyword_generator')
        if not self.prompt_template:
            raise ValueError("Keyword generator prompt 'prompts.keyword_generator' not found in config.yaml")

    def generate_for_scenes(self, scenes: list) -> list:
        for scene in scenes:
            try:
                prompt = self.prompt_template.format(
                    scene_text=scene["text"], 
                    duration=scene["duration"]
                )
                response_text = self.llm_manager.generate_with_failover(prompt)
                parsed_data = _parse_llm_json_response(response_text)
                
                if parsed_data and isinstance(parsed_data, dict) and 'scenes' in parsed_data:
                    # The new logic: add a 'scenes' key containing the list of shots.
                    scene['scenes'] = parsed_data.get('scenes', [])
                else:
                    # Fallback if parsing fails or format is wrong
                    scene['scenes'] = []
            except Exception as e:
                log.error(f"Failed to generate keywords for scene: \"{scene['text'][:30]}...\"。", exc_info=True)
                scene['scenes'] = []
        return scenes
