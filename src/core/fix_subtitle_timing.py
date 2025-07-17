import re
from typing import List, Dict


class FixSubtitleTiming:
    @staticmethod
    def fix(srt_text: str, gap_tolerance_ms: int = 0, force_start_at_zero: bool = True) -> str:
        """
        主入口：修复字幕时间对齐，返回新的 SRT 文本。
        :param srt_text: 原始字幕文本内容
        :param gap_tolerance_ms: 容差（毫秒），默认 0，表示只要不一致就修正
        :param force_start_at_zero: 是否强制将第一句字幕起始时间设置为 0 秒
        """
        segments = FixSubtitleTiming._parse(srt_text)
        segments = FixSubtitleTiming._adjust(segments, gap_tolerance_ms)

        if force_start_at_zero and segments and segments[0]['start'] > 0.0:
            segments[0]['start'] = 0.0  # 强制归零

        return FixSubtitleTiming._render(segments)

    @staticmethod
    def _parse(srt_text: str) -> List[Dict]:
        """
        将 SRT 文本解析为结构化字幕段落（start, end, text）
        时间单位为 float 秒
        """
        pattern = re.compile(
            r"(\d+)\n"
            r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n"
            r"(.*?)\n(?:\n|$)",
            re.DOTALL
        )
        matches = pattern.findall(srt_text)

        segments = []
        for _, start, end, text in matches:
            segments.append({
                'start': FixSubtitleTiming._to_seconds(start),
                'end': FixSubtitleTiming._to_seconds(end),
                'text': text.replace('\n', ' ').strip()
            })

        return segments

    @staticmethod
    def _adjust(segments: List[Dict], gap_tolerance_ms: int) -> List[Dict]:
        """
        修正时间：确保每句字幕结束时间对齐下一句的开始时间（超过容差时修正）。
        """
        segments.sort(key=lambda x: x['start'])
        adjusted = []

        for i, entry in enumerate(segments):
            corrected = entry.copy()
            if i < len(segments) - 1:
                next_start = segments[i + 1]['start']
                gap = abs(corrected['end'] - next_start) * 1000
                if gap > gap_tolerance_ms:
                    corrected['end'] = next_start
            adjusted.append(corrected)

        return adjusted

    @staticmethod
    def _render(segments: List[Dict]) -> str:
        """
        将结构化字幕段落重新转回 SRT 格式文本
        """
        srt_blocks = []
        for i, seg in enumerate(segments):
            start = FixSubtitleTiming._to_srt_time(seg['start'])
            end = FixSubtitleTiming._to_srt_time(seg['end'])
            block = f"{i + 1}\n{start} --> {end}\n{seg['text']}\n"
            srt_blocks.append(block)

        return "\n".join(srt_blocks)

    @staticmethod
    def _to_seconds(ts: str) -> float:
        h, m, s_ms = ts.split(':')
        s, ms = s_ms.split(',')
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    @staticmethod
    def _to_srt_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
