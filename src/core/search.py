# -*- coding: utf-8 -*-                        # 指定源码文件编码为 UTF-8，支持中文字符
import logging                                 # 导入日志记录模块
from tqdm import tqdm                          # 导入进度条库，用于显示处理进度
from thefuzz import fuzz                       # 导入字符串模糊匹配工具（Levenshtein 距离）
from sentence_transformers import util         # 导入语义相似度计算工具
from .model_loader import ModelLoader          # 导入自定义模型加载器
from .text import TextProcessor                # 导入文本处理模块

class Searcher:
    """
    搜索器类：负责将文本与音频转录内容进行对齐，并执行语义搜索。
    """
    def __init__(self, model_loader: ModelLoader, text_processor: TextProcessor):
        self.sentence_model = model_loader.get_sentence_model()  # 加载语义嵌入模型
        self.text_processor = text_processor                     # 初始化文本处理器

    def _encode_text(self, text: str):
        """将输入文本编码为语义嵌入向量。"""
        if not self.sentence_model:                              # 模型未加载时输出错误日志
            logging.error("SentenceTransformer model not loaded. Cannot encode text.")
            return None
        return self.sentence_model.encode(text, show_progress_bar=False)  # 调用模型进行编码

    def linear_align(self, target_lines, whisper_words, debug=False):
        """将目标文本与 Whisper 模型转录的单词进行线性窗口对齐。"""
        aligned_results = []             # 保存最终对齐结果
        used_word_indices = set()        # 保存已使用的音频词索引，避免重复匹配
        whisper_idx = 0                  # 当前搜索的起始索引（滑动窗口）

        for line in tqdm(target_lines, desc="Linearly Aligning Text"):  # 为每一行文本做对齐
            normalized_line = self.text_processor.normalize(line)       # 对文本进行标准化处理
            if not normalized_line:                                     # 若处理后为空则跳过
                continue

            search_start_idx = whisper_idx                # 定义搜索窗口起始位置
            max_search_words = 150                        # 最大搜索窗口长度
            search_window_size = min(len(normalized_line) * 3 + 20, max_search_words)  # 根据文本长度动态计算窗口
            best_score = -1                               # 初始化最佳匹配得分
            best_match_info = None                        # 保存最佳匹配结果信息

            search_end_idx = min(search_start_idx + search_window_size, len(whisper_words))  # 定义搜索窗口结束索引

            if search_start_idx >= len(whisper_words):    # 若起始位置越界，则跳过该行
                if debug: logging.info(f"DEBUG: No more whisper words to search for line: '{line}'")
                continue

            # 双层循环穷举所有可能的子序列
            for i in range(search_start_idx, search_end_idx):
                for j in range(i, search_end_idx):
                    sub_sequence = whisper_words[i:j+1]   # 获取当前位置的词组子序列
                    if not sub_sequence: continue

                    sub_sequence_text = "".join([w['word'] for w in sub_sequence])  # 拼接子序列文本
                    normalized_sub_sequence = self.text_processor.normalize(sub_sequence_text)  # 对音频文本进行标准化

                    current_score = fuzz.token_set_ratio(normalized_line, normalized_sub_sequence)  # 计算模糊匹配得分

                    # 保存最佳得分与对应的序列索引
                    if current_score > best_score:
                        best_score = current_score
                        best_match_info = {
                            "words": sub_sequence,           # 匹配的词列表
                            "start_idx": i,                  # 起始索引
                            "end_idx": j + 1,                # 结束索引（非闭区间）
                        }

            match_threshold = 75     # 匹配得分阈值（超过即认为匹配成功）

            if best_score >= match_threshold:  # 若匹配成功则构造结果条目
                aligned_results.append({
                    "text": line,                                           # 原始文本
                    "start": best_match_info['words'][0]['start'],         # 匹配段起始时间
                    "end": best_match_info['words'][-1]['end'],            # 匹配段结束时间
                    "embedding": self._encode_text(line),                  # 文本语义嵌入
                    "source": "text_file"                                  # 来源标记
                })
                whisper_idx = best_match_info['end_idx']                   # 更新搜索起点
                for k in range(best_match_info['start_idx'], best_match_info['end_idx']):
                    used_word_indices.add(k)                               # 标记已使用的音频词索引
            else:
                whisper_idx += max(1, len(normalized_line) // 5)          # 若匹配失败则向后滑动窗口
                whisper_idx = min(whisper_idx, len(whisper_words))        # 防止越界

        return aligned_results, used_word_indices  # 返回对齐结果与已使用音频索引

    def search(self, query_text, aligned_data):
        """在已对齐的数据中进行语义查询匹配。"""
        query_embedding = self._encode_text(query_text)     # 编码查询文本为嵌入向量
        if query_embedding is None:                         # 编码失败则记录错误并返回空
            logging.error("Could not encode query text.")
            return None

        best_match = None                                   # 保存最佳匹配结果
        max_similarity = -1.0                               # 初始化最大相似度值

        for item in aligned_data:                           # 遍历所有已对齐段落
            segment_embedding = item.get('embedding')       # 获取段落的嵌入向量
            if segment_embedding is None:
                continue

            similarity = util.cos_sim(query_embedding, segment_embedding).item()  # 计算余弦相似度

            if similarity > max_similarity:                 # 更新最大相似度并保存最佳匹配信息
                max_similarity = similarity
                best_match = {
                    "text": item.get('text'),              # 匹配文本内容
                    "start": item.get('start'),            # 起始时间
                    "end": item.get('end'),                # 结束时间
                    "similarity": similarity               # 相似度值
                }

        return best_match                                   # 返回最佳匹配结果（语义最相近的片段）
