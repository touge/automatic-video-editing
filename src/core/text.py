# -*- coding: utf-8 -*-                # 设置源码文件编码为UTF-8，支持中文字符
import logging                         # 引入日志模块，用于记录错误信息
import warnings                        # 引入警告模块，用于忽略特定警告
import re                              # 引入正则表达式模块，用于文本清洗与分割
import cn2an                           # 中文数字与阿拉伯数字互转的库
from .model_loader import ModelLoader # 从当前模块引入模型加载器

class TextProcessor:
    """
    文本处理类：包括规范化、时间格式化、句子分割等功能。
    """
    def __init__(self, model_loader: ModelLoader):
        # 初始化时从 ModelLoader 获取 OpenCC 实例（用于繁简转换）
        self.cc = model_loader.get_opencc()

    def normalize(self, text: str) -> str:
        """
        对文本进行深度规范化：
        - 繁体转简体
        - 中文数字转阿拉伯数字
        - 移除标点，转为小写
        """
        if not self.cc:
            # 若 OpenCC 模型未加载，则报错并返回原文
            logging.error("OpenCC model not loaded. Cannot normalize text.")
            return text

        # Step 1: 繁体转简体
        simplified_text = self.cc.convert(text)

        # Step 2: 中文数字转阿拉伯数字（使用 cn2an）
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)  # 忽略 UserWarning
            try:
                normalized_text = cn2an.transform(simplified_text, "cn2an")
            except (ValueError, KeyError):
                # 转换失败时回退为简体文本（不改变数字）
                normalized_text = simplified_text
        
        # Step 3: 移除非字母数字字符（保留汉字和英文）并转小写
        return re.sub(r'[^\w]', '', normalized_text).lower()

    @staticmethod
    def format_time(seconds: float) -> str:
        """
        将秒数转为 SRT 字幕格式（HH:MM:SS,毫秒）
        """
        assert seconds >= 0, "Cannot format negative seconds"  # 校验输入
        m, s = divmod(seconds, 60)       # 秒转分钟
        h, m = divmod(m, 60)             # 分钟转小时
        # 格式化成 "HH:MM:SS,ms" 字符串，毫秒为小数部分 * 1000
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s - int(s)) * 1000):03d}"

    @staticmethod
    def split_and_clean_sentences(text: str) -> list[str]:
        """
        拆分文本为句子，去除多余标点和空串：
        - 按句号、逗号、问号等断句
        - 清理每句末尾标点
        """
        if not text:
            return []  # 空文本直接返回空列表

        # 使用正则按句子尾部的中文/英文标点进行分割
        sentences = re.split(r'(?<=[，。？：；,.:;?!])', text)
        
        cleaned_sentences = []
        for sentence in sentences:
            s = sentence.strip()  # 去除前后空格
            if s:
                # 去掉句尾多余标点（防止重复标点）
                s = re.sub(r'[，。？：；,.:;?!]+$', '', s)
                cleaned_sentences.append(s)
        
        return cleaned_sentences  # 返回干净句子列表

    @staticmethod
    def smart_split(text: str, min_len: int = 5, max_len: int = 20) -> list[str]:
        """
        智能拆分句子为多个短句：
        - 保证每段长度在[min_len, max_len]之间
        - 优先在标点、词语边界处断开
        - 中文专用，英文句子需适配扩展
        """
        if len(text) <= max_len:
            return [text]  # 不需要拆分

        punctuation_breaks = ['，', '。', '？', '；', '：', ',', '.', '?', ';', ':']
        result = []
        start = 0
        while start < len(text):
            # 查找合适断点（从 max_len 往回找，优先标点）
            end = min(len(text), start + max_len)
            found = False
            for i in range(end, start + min_len - 1, -1):  # 倒序查找断点
                if text[i - 1] in punctuation_breaks:
                    result.append(text[start:i].strip())
                    start = i
                    found = True
                    break
            if not found:  # 没有标点断点，硬切（保证不低于 min_len）
                result.append(text[start:end].strip())
                start = end

        return [s for s in result if len(s) >= min_len]  # 过滤掉过短片段
