import ollama
import os
import json

class SceneSplitter:
    def __init__(self, config: dict, task_id: str):
        self.config = config
        self.task_id = task_id
        self.ollama_config = config.get('ollama', {})
        self.client = ollama.Client(host=self.ollama_config.get('host'))
        # 参数可以根据你的硬件和模型性能进行调整
        splitter_config = config.get('scene_detection', {}).get('splitter', {})
        self.chunk_size = splitter_config.get('chunk_size', 50)
        self.overlap = splitter_config.get('overlap', 10)

        # 创建用于缓存区块分割结果的目录
        self.cache_dir = os.path.join("storage", "tasks", self.task_id, "scene_split_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_split_points_from_chunk(self, chunk_segments: list) -> list[int]:
        """
        将一个文本区块发送给LLM，并识别出场景切换点。
        返回一个列表，包含每个场景最后一行字幕的行号（相对于区块内部）。
        """
        numbered_text = "\n".join([f"{i}: {seg['text']}" for i, seg in enumerate(chunk_segments)])

        prompt = f"""You are an expert video editor. Your task is to split a transcript into logical scenes.
Read the following numbered transcript. Identify the line numbers where a natural scene break occurs. A scene break is a significant change in topic, time, or location.
List only the line numbers of the LAST line of each scene, separated by commas. For example: 15, 28, 45

Transcript:
{numbered_text}

Line numbers of scene breaks:"""

        try:
            response = self.client.chat(
                model=self.ollama_config.get('model'),
                messages=[{'role': 'user', 'content': prompt}],
                options={'temperature': 0.0} # 使用低温以获得更确定的结果
            )
            content = response['message']['content']
            split_points = [int(n.strip()) for n in content.split(',') if n.strip().isdigit()]
            return sorted(split_points)
        except Exception as e:
            print(f"警告: 调用Ollama进行场景分割时出错: {e}. 该区块将不会被分割。")
            return []

    def split(self, segments: list) -> list:
        if not segments:
            return []

        print(f"开始对 {len(segments)} 个字幕片段进行分块场景分割...")
        print(f"配置: chunk_size={self.chunk_size}, overlap={self.overlap}")

        all_split_indices = set()
        step = self.chunk_size - self.overlap
        if step <= 0:
            print("错误: chunk_size 必须大于 overlap。请检查 config.yaml。将使用默认步长。")
            step = self.chunk_size // 2 if self.chunk_size > 1 else 1

        for i in range(0, len(segments), step):
            chunk_start = i
            chunk_end = i + self.chunk_size
            chunk = segments[chunk_start:chunk_end]

            if not chunk:
                continue

            print(f"正在处理区块 (片段 {chunk_start}-{chunk_end-1})...")

            cache_file = os.path.join(self.cache_dir, f"chunk_{chunk_start}_{chunk_end-1}.json")

            relative_split_points = []
            if os.path.exists(cache_file):
                print(f"  -> 从缓存加载: {os.path.basename(cache_file)}")
                with open(cache_file, 'r', encoding='utf-8') as f:
                    relative_split_points = json.load(f)
            else:
                print("  -> 无缓存，正在调用LLM...")
                relative_split_points = self._get_split_points_from_chunk(chunk)
                print(f"  -> LLM返回分割点: {relative_split_points}。正在写入缓存...")
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(relative_split_points, f)

            for point in relative_split_points:
                if 0 <= point < len(chunk):
                    absolute_index = chunk_start + point
                    all_split_indices.add(absolute_index)

        # 确保最后一个片段也被视为一个场景的结尾
        all_split_indices.add(len(segments) - 1)
        sorted_split_indices = sorted(list(all_split_indices))

        print(f"分割完成，找到 {len(sorted_split_indices)} 个场景。正在组合场景...")

        scenes = []
        last_split = -1
        for split_index in sorted_split_indices:
            scene_segments = segments[last_split + 1 : split_index + 1]
            if scene_segments:
                start_time = scene_segments[0]['start']
                end_time = scene_segments[-1]['end']
                full_text = " ".join(s['text'] for s in scene_segments)
                scenes.append({
                    "scene_start": start_time,
                    "scene_end": end_time,
                    "duration": round(end_time - start_time, 2),
                    "text": full_text,
                    "segments": scene_segments
                })
            last_split = split_index

        return scenes