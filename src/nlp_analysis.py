import os
import json
from src.logger import log
from src.providers.llm import LlmManager
from src.color_utils import (
    print_colored,
    print_error,
    print_warning,
    print_success,
    print_info,
)
# 1. 将提示词模板定义为常量，以便复用和修改
PROMPT_TEMPLATE = """You are a creative director and shot-list creator for video production.
Based on the scene description, your task is to:
1.  Add appropriate punctuation to the original text to make it a natural, readable sentence.
2.  Create a list of **up to 3** English keywords, suitable for searching stock video footage. These should be concrete, visual, and action-oriented. **The keywords must be sorted by relevance, with the most important one first.**
3.  Create a list of **up to 3** Chinese keywords that describe a sequence of shots, like a storyboard. **The keywords must be sorted by relevance, with the most important one first.**

You MUST return your response as a single, valid JSON object. Do not include any other text or explanations.

**Example:**
Scene Description: "一个24岁的中国女孩远赴意大利与父母团聚在异国他乡勤劳打拼"
Your JSON Response:
{{
  "punctuated_text": "一个24岁的中国女孩，远赴意大利与父母团聚，在异国他乡勤劳打拼。",
  "keywords_en": ["woman on airplane", "family hug at airport", "working hard abroad"],
  "keywords_cn": ["一个女人坐飞机", "父母机场接机", "在异国努力工作"]
}}

Now, process the following scene.

Scene Description: "{scene_text}"

Your JSON Response:"""


def _parse_llm_json_response(raw_text: str) -> dict | None:
    """
    从LLM的原始输出中稳健地解析出JSON对象。
    它会找到第一个'{'和最后一个'}'来提取JSON部分，以应对模型返回多余文本的情况。
    """
    try:
        # 找到JSON对象的开始和结束位置
        start_index = raw_text.find('{')
        end_index = raw_text.rfind('}')
        
        if start_index == -1 or end_index == -1 or start_index > end_index:
            log.warning("LLM响应中未找到有效的JSON对象。 响应: %r", raw_text[:200] + "...")
            return None
            
        json_str = raw_text[start_index : end_index + 1]
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        log.error("解析LLM的JSON响应失败: %s", e, exc_info=True)
        log.debug("原始响应: %r", raw_text)
        return None

def extract_keywords_from_scenes(scenes: list, config: dict) -> list:
    """
    从场景文本中提取富有描述性的关键词。
    使用 LlmManager 动态选择配置的LLM服务。
    :param scenes: 场景字典列表。
    :param config: 包含 llm_providers 配置的字典。
    :return: 更新了关键词的场景列表。
    """
    llm_manager = LlmManager(config)
    llm_provider = llm_manager.default

    if not llm_provider:
        log.error("没有可用的LLM提供者。请检查config.yaml中的'llm_providers'配置。将跳过关键词提取。")
        for scene in scenes:
            scene['keywords_en'] = []
            scene['keywords_cn'] = []
        return scenes

    print_info(f"正在使用 LLM provider '{llm_provider.name}' 提取关键词...")

    for scene in scenes:
        try:
            prompt = PROMPT_TEMPLATE.format(scene_text=scene["text"])
            response_text = llm_provider.generate(prompt)
            parsed_data = _parse_llm_json_response(response_text)
            
            if parsed_data:
                scene.pop('keywords', None) # 移除旧的、空的keywords字段
                scene['text'] = parsed_data.get('punctuated_text', scene['text'])
                scene['keywords_en'] = parsed_data.get('keywords_en', [])
                scene['keywords_cn'] = parsed_data.get('keywords_cn', [])
                print_info("场景: \"%s...\" -> EN关键词: %s", scene['text'][:30], scene.get('keywords_en'))
            else:
                scene['keywords_en'] = []
                scene['keywords_cn'] = []
        except Exception as e:
            log.error(f"调用 LLM provider '{llm_provider.name}' 失败，场景: \"%s...\"。", scene['text'][:30], exc_info=True)
            scene['keywords_en'] = []
            scene['keywords_cn'] = []
            
    return scenes
