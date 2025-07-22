"""
fix_subtitle_timing.py

字幕时间修复模块，用于调整 SRT 字幕文件中的起止时间对齐，
支持自定义容差修正并强制首段起始时间归零。核心类 FixSubtitleTiming
包含解析、调整、渲染三个步骤，可用于字幕对齐优化及时间规范化任务。

功能亮点：
- 支持词间容差对齐
- 自动归零第一段时间
- SRT 转结构化段落再重构输出
"""

import re  # 引入正则表达式模块，用于解析 SRT 字幕文本结构
from typing import List, Dict  # 类型注解模块，提升代码清晰度


class SubtitleTimingFixer:
    @staticmethod
    def fix(srt_text: str, gap_tolerance_ms: int = 0, force_start_at_zero: bool = True) -> str:
        """
        主方法：修复字幕时间对齐并返回修复后的 SRT 文本
        :param srt_text: 输入的原始字幕文本内容（SRT 格式）
        :param gap_tolerance_ms: 字幕段落间的容差阈值（毫秒），超过则修正
        :param force_start_at_zero: 是否强制将第一段起始时间设为 0 秒
        """
        segments = SubtitleTimingFixer._parse(srt_text)  # 步骤一：解析为结构化段落
        segments = SubtitleTimingFixer._adjust(segments, gap_tolerance_ms)  # 步骤二：应用容差修正

        # 步骤三：若启用强制起始归零，且首段时间大于 0，则归零
        if force_start_at_zero and segments and segments[0]['start'] > 0.0:
            segments[0]['start'] = 0.0

        return SubtitleTimingFixer._render(segments)  # 步骤四：渲染为 SRT 格式文本

    @staticmethod
    def _parse(srt_text: str) -> List[Dict]:
        """
        将 SRT 文本解析为结构化段落信息列表
        :return: 每段包含起始时间、结束时间和文本内容
        """
        # 匹配字幕段落的编号、起止时间和内容
        pattern = re.compile(
            r"(\d+)\n"  # 匹配字幕序号
            r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n"  # 匹配时间段
            r"(.*?)\n(?:\n|$)",  # 匹配字幕文本
            re.DOTALL  # 支持跨行匹配
        )
        matches = pattern.findall(srt_text)  # 查找所有匹配段落

        segments = []
        for _, start, end, text in matches:
            segments.append({
                'start': SubtitleTimingFixer._to_seconds(start),  # 转换起始时间为秒
                'end': SubtitleTimingFixer._to_seconds(end),  # 转换结束时间为秒
                'text': text.replace('\n', ' ').strip()  # 清理换行并去除首尾空格
            })
        return segments

    @staticmethod
    def _adjust(segments: List[Dict], gap_tolerance_ms: int) -> List[Dict]:
        """
        调整字幕时间：确保每段结束时间对齐下一段起始时间（按容差修正）
        :param segments: 原始段落列表
        :param gap_tolerance_ms: 时间容差阈值（毫秒）
        :return: 修正后的段落列表
        """
        segments.sort(key=lambda x: x['start'])  # 按起始时间升序排序
        adjusted = []

        for i, entry in enumerate(segments):
            corrected = entry.copy()  # 拷贝原始段落
            if i < len(segments) - 1:  # 不是最后一段时可修正结束时间
                next_start = segments[i + 1]['start']
                gap = abs(corrected['end'] - next_start) * 1000  # 计算结束与下一段起始的间隔（毫秒）
                if gap > gap_tolerance_ms:  # 超过容差则修改结束时间
                    corrected['end'] = next_start
            adjusted.append(corrected)  # 添加修正结果
        return adjusted

    @staticmethod
    def _render(segments: List[Dict]) -> str:
        """
        渲染结构化段落为 SRT 字幕文本
        :param segments: 修正后的段落列表
        :return: 重新生成的 SRT 字幕文本
        """
        srt_blocks = []
        for i, seg in enumerate(segments):
            start = SubtitleTimingFixer._to_srt_time(seg['start'])  # 转换起始时间格式
            end = SubtitleTimingFixer._to_srt_time(seg['end'])  # 转换结束时间格式
            block = f"{i + 1}\n{start} --> {end}\n{seg['text']}\n"  # 构建 SRT 块
            srt_blocks.append(block)
        return "\n".join(srt_blocks)  # 合并所有块为完整字幕文本

    @staticmethod
    def _to_seconds(ts: str) -> float:
        """
        将 SRT 时间字符串转换为浮点秒数
        :param ts: 时间字符串（格式如 00:01:23,456）
        :return: 秒数
        """
        h, m, s_ms = ts.split(':')
        s, ms = s_ms.split(',')
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    @staticmethod
    def _to_srt_time(sec: float) -> str:
        """
        将秒数转换为 SRT 标准时间格式
        :param sec: 秒数（float）
        :return: 时间字符串（格式如 00:01:23,456）
        """
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
