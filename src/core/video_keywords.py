# ─── video_keywords.py ──────────────────────────────────────────────────────────
import os
import json
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import AgglomerativeClustering
import ollama

def dedupe_and_fill(keywords, target=3, threshold=0.6, fallback=None):
    """
    对 keywords 做语义去重，保留每簇最先出现的词。
    如果去重后数量 < target，则用 fallback 补齐。
    """
    if not keywords:
        return (fallback or [])[:target]

    vec = TfidfVectorizer().fit_transform(keywords)
    clustering = AgglomerativeClustering(
        n_clusters=None,
        affinity='cosine',
        linkage='average',
        distance_threshold=1 - threshold
    ).fit(vec.toarray())
    labels = clustering.labels_

    unique, seen = [], set()
    for idx, lab in enumerate(labels):
        if lab not in seen:
            unique.append(keywords[idx])
            seen.add(lab)

    # 补齐
    if len(unique) < target:
        extra = fallback or []
        for w in extra:
            if w not in unique:
                unique.append(w)
            if len(unique) == target:
                break

    return unique[:target]


class VideoKeywordService:
    def __init__(self, config):
        # 你的已有初始化逻辑
        self.config = config
        self.ollama_config = config.get('ollama', {})
        self.ollama_client = ollama.Client(host=self.ollama_config.get('host'))
        prompts = config['prompts']['asset_keyword_generator']
        self.system_prompt = prompts['system']
        self.user_template = prompts['user']

    def generate_keywords(self, scene_text):
        # 1. 填充 Prompt
        user_prompt = self.user_template.format(scene_text=scene_text)

        # 2. 调用 Ollama 得到原始答案
        resp = self.ollama_client.chat(
            model=self.ollama_config['model'],
            system=self.system_prompt,
            user=user_prompt
        )
        data = json.loads(resp)

        # 3. 用去重+补齐函数处理英文和中文关键词
        fallback_en = ["healthy lifestyle", "wellness routine", "exercise motion"]
        fallback_cn = ["健康生活方式", "养生日常", "运动镜头"]

        en_unique = dedupe_and_fill(
            data.get("keywords_en", []),
            target=3,
            threshold=0.6,
            fallback=fallback_en
        )
        cn_unique = dedupe_and_fill(
            data.get("keywords_cn", []),
            target=3,
            threshold=0.6,
            fallback=fallback_cn
        )

        # 4. 最终返回
        return {
            "punctuated_text": data.get("punctuated_text", ""),
            "keywords_en": en_unique,
            "keywords_cn": cn_unique
        }
