import ollama
import json
from src.logger import log

def _parse_llm_json_response(raw_text: str) -> dict | None:
    """
    从LLM的原始输出中稳健地解析出JSON对象。
    它会找到第一个'{'和最后一个'}'来提取JSON部分，以应对模型返回多余文本的情况。
    """
    try:
        start_index = raw_text.find('{')
        end_index = raw_text.rfind('}')
        
        if start_index == -1 or end_index == -1 or start_index > end_index:
            log.warning("LLM 响应中未找到有效的 JSON 对象。响应: %r",raw_text[:200] + "...")
            return None
            
        json_str = raw_text[start_index : end_index + 1]
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        log.error("解析 LLM 的 JSON 响应失败: %s", e)
        log.debug("原始响应内容: %r", raw_text)
        return None

class KeywordGenerator:
    def __init__(self, config: dict):
        self.ollama_config = config.get('ollama', {})
        if not self.ollama_config.get('model'):
            raise ValueError("Ollama未在config.yaml中配置。")
        self.client = ollama.Client(host=self.ollama_config.get('host', 'http://localhost:11434'))
        self.prompt_template = config.get('prompts', {}).get('keyword_generator')
        if not self.prompt_template:
            raise ValueError("Keyword generator prompt 'prompts.keyword_generator' not found in config.yaml")

    def generate_for_scenes(self, scenes: list) -> list:
        for scene in scenes:
            try:
                prompt = self.prompt_template.format(scene_text=scene["text"])
                response = self.client.generate(model=self.ollama_config['model'], prompt=prompt)
                parsed_data = _parse_llm_json_response(response['response'])
                if parsed_data:
                    scene.pop('keywords', None) # 移除旧的、空的keywords字段
                    scene['text'] = parsed_data.get('punctuated_text', scene['text'])
                    scene['keywords_en'] = parsed_data.get('keywords_en', [])
                    scene['keywords_cn'] = parsed_data.get('keywords_cn', [])
                else:
                    scene['keywords_en'] = []
                    scene['keywords_cn'] = []
            except Exception as e:
                log.error(f"调用 Ollama API 失败，场景: \"{scene['text'][:30]}...\"。", exc_info=True)
                scene['keywords_en'] = []
                scene['keywords_cn'] = []
        return scenes