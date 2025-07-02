import google.generativeai as genai
import ollama
import os
import json

from src.logger import log
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

def _extract_keywords_with_gemini(scenes: list, api_key: str) -> list:
    """
    使用 Google Gemini API 提取关键词。
    :param scenes: 场景字典列表。
    :param api_key: Google Gemini API 密钥。
    :return: 更新了关键词的场景列表。
    """
    print_info("正在使用 Google Gemini API 提取关键词...")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-pro-latest')

    for scene in scenes:
        try:
            prompt = PROMPT_TEMPLATE.format(scene_text=scene["text"])
            response = model.generate_content(prompt)
            parsed_data = _parse_llm_json_response(response.text)
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
            log.error("调用 Gemini API 失败，场景: \"%s...\"。", scene['text'][:30], exc_info=True)
            scene['keywords_en'] = []
            scene['keywords_cn'] = []
    return scenes

def _extract_keywords_with_ollama(scenes: list, model_name: str, host: str) -> list:
    """
    使用本地 Ollama 服务提取关键词。
    """
    print_info("正在使用 Ollama (%s @ %s) 提取关键词...", model_name, host)
    try:
        client = ollama.Client(host=host)
        # 检查模型是否已在本地拉取
        client.list()
    except Exception as e:
        log.error("无法连接到 Ollama 服务 at %s。请确保 Ollama 正在运行。", host, exc_info=True)
        for scene in scenes:
            scene['keywords_en'] = []
            scene['keywords_cn'] = []
        return scenes

    for scene in scenes:
        try:
            prompt = PROMPT_TEMPLATE.format(scene_text=scene["text"])
            # 移除 format="json"，让我们的解析器来处理，这样更稳定
            response = client.generate(model=model_name, prompt=prompt)
            parsed_data = _parse_llm_json_response(response['response'])
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
            log.error("调用 Ollama API 失败，场景: \"%s...\"。", scene['text'][:30], exc_info=True)
            scene['keywords_en'] = []
            scene['keywords_cn'] = []
    return scenes

def extract_keywords_from_scenes(scenes: list, config: dict) -> list:
    """
    从场景文本中提取富有描述性的关键词。
    根据配置优先使用 Ollama，其次是 Gemini。
    :param scenes: 场景字典列表。
    :param config: 包含 API 密钥和模型配置的字典。
    :return: 更新了关键词的场景列表。
    """
    gemini_config = config.get('gemini', {})
    ollama_config = config.get('ollama', {})

    # 优先使用 Ollama
    if ollama_config.get('model'):
        return _extract_keywords_with_ollama(
            scenes,
            model_name=ollama_config['model'],
            host=ollama_config.get('host', 'http://localhost:11434')
        )
    # 如果 Ollama 未配置，则尝试 Gemini
    elif gemini_config.get('api_key') and "YOUR_GEMINI_API_KEY_HERE" not in gemini_config.get('api_key'):
        return _extract_keywords_with_gemini(scenes, api_key=gemini_config['api_key'])
    # 如果两者都未配置
    else:
        log.error("Gemini 或 Ollama 均未在 config.yaml 中正确配置。程序将跳过关键词提取。")
        for scene in scenes:
            scene['keywords_en'] = []
            scene['keywords_cn'] = []
        return scenes
