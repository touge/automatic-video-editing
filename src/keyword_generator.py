import ollama
import os
import json


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
        start_index = raw_text.find('{')
        end_index = raw_text.rfind('}')
        
        if start_index == -1 or end_index == -1 or start_index > end_index:
            print(f"警告: LLM响应中未找到有效的JSON对象。 响应: {raw_text[:200]}...")
            return None
            
        json_str = raw_text[start_index : end_index + 1]
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"错误: 解析LLM的JSON响应失败: {e}")
        print(f"原始响应: {raw_text}")
        return None

class KeywordGenerator:
    def __init__(self, config: dict):
        self.ollama_config = config.get('ollama', {})
        if not self.ollama_config.get('model'):
            raise ValueError("Ollama未在config.yaml中配置。")
        self.client = ollama.Client(host=self.ollama_config.get('host', 'http://localhost:11434'))

    def generate_for_scenes(self, scenes: list) -> list:
        print(f"正在使用 Ollama ({self.ollama_config['model']}) 生成关键词...")
        for scene in scenes:
            try:
                prompt = PROMPT_TEMPLATE.format(scene_text=scene["text"])
                response = self.client.generate(model=self.ollama_config['model'], prompt=prompt)
                parsed_data = _parse_llm_json_response(response['response'])
                if parsed_data:
                    scene.pop('keywords', None) # 移除旧的、空的keywords字段
                    scene['text'] = parsed_data.get('punctuated_text', scene['text'])
                    scene['keywords_en'] = parsed_data.get('keywords_en', [])
                    scene['keywords_cn'] = parsed_data.get('keywords_cn', [])
                    print(f"场景: \"{scene['text'][:30]}...\" -> EN关键词: {scene.get('keywords_en')}")
                else:
                    scene['keywords_en'] = []
                    scene['keywords_cn'] = []
            except Exception as e:
                print(f"错误: 调用 Ollama API 失败，场景: \"{scene['text'][:30]}...\"。错误信息: {e}")
                scene['keywords_en'] = []
                scene['keywords_cn'] = []
        return scenes