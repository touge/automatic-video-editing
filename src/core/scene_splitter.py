import ollama
import os
import json
from src.logger import log
from tqdm import tqdm
import math
from src.color_utils import (
    print_colored,
    print_error,
    print_warning,
    print_success,
    print_info,
)
class SceneSplitter:
    def __init__(self, config: dict, task_id: str):
        self.config = config
        self.task_id = task_id
        self.ollama_config = config.get('ollama', {})
        if not self.ollama_config.get('model'):
            raise ValueError("Ollama model not configured in config.yaml")

        # 采用“乐观执行”策略，直接初始化客户端，在实际调用时处理错误。
        self.client = ollama.Client(
            host=self.ollama_config.get('host'),
            timeout=self.ollama_config.get('timeout', 60)
        )
        # 从配置中加载提示词模板
        prompts_config = self.config.get('prompts', {})
        self.prompt_template = prompts_config.get('scene_splitter')
        if not self.prompt_template:
            raise ValueError("Scene splitter prompt 'prompts.scene_splitter' not found in config.yaml")
        # 参数可以根据你的硬件和模型性能进行调整
        splitter_config = config.get('scene_detection', {}).get('splitter', {})
        self.chunk_size = splitter_config.get('chunk_size', 50)
        self.overlap = splitter_config.get('overlap', 10)

        # 创建用于缓存区块分割结果的目录
        self.cache_dir = os.path.join("storage", "tasks", self.task_id, ".cache","scenes_split")
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_split_points_from_chunk(self, chunk_segments: list) -> list[int]:
        """
        将一个文本区块发送给LLM，并识别出场景切换点。
        返回一个列表，包含每个场景最后一行字幕的行号（相对于区块内部）。
        """
        numbered_text = "\n".join([f"{i}: {seg['text']}" for i, seg in enumerate(chunk_segments)])

        prompt = self.prompt_template.format(numbered_text=numbered_text)
        try:
            response = self.client.chat(
                model=self.ollama_config.get('model'),
                messages=[{'role': 'user', 'content': prompt}],
                options={'temperature': 0.0} # 使用低温以获得更确定的结果
            )
            content = response['message']['content']
            # 使用 set 来处理LLM可能返回的重复数字
            raw_points = [int(n.strip()) for n in content.split(',') if n.strip().isdigit()]
            split_points = sorted(list(set(raw_points))) # 去重并排序
            return split_points
        except ollama.ResponseError as e:
            # 捕获Ollama返回的特定错误，例如模型未找到
            if "model" in e.error.lower() and "not found" in e.error.lower():
                model_name = self.ollama_config.get('model')
                log.error(f"Ollama错误: 模型 '{model_name}' 未找到。")
                log.error(f"请确认模型名称是否正确，或通过 `ollama pull {model_name}` 拉取。")
            else:
                log.error(f"调用Ollama时发生API错误: {e.error}")
            raise e # 重新抛出异常，中断程序
        except Exception as e:
            log.warning(f"调用Ollama进行场景分割时出错: {e}. 该区块将不会被分割。", exc_info=True)
            return []

    def _construct_scenes_for_chunk(self, chunk_segments: list, split_points: list) -> list:
        """
        为单个区块构建场景字典列表，用于缓存。
        这使得缓存文件具有可读性。
        """
        scenes_for_cache = []
        last_split = -1
        
        # 确保区块的最后一个片段也被视为分割点，以便构建场景
        all_points = sorted(list(set(split_points + [len(chunk_segments) - 1])))

        for point in all_points:
            start_index = last_split + 1
            end_index = point
            
            if start_index > end_index:
                continue

            scene_segs = chunk_segments[start_index : end_index + 1]
            if not scene_segs:
                continue
                
            text = " ".join(s['text'] for s in scene_segs)
            
            scenes_for_cache.append({
                "start_line_in_chunk": start_index,
                "end_line_in_chunk": end_index,
                "text": text
            })
            last_split = end_index
            
        return scenes_for_cache

    def split(self, segments: list) -> list:
        if not segments:
            return []

        all_split_indices = set()
        step = self.chunk_size - self.overlap
        if step <= 0:
            log.error("错误: chunk_size 必须大于 overlap。请检查 config.yaml。将使用默认步长。")
            step = self.chunk_size // 2 if self.chunk_size > 1 else 1

        num_chunks = math.ceil(len(segments) / step)
        pbar = tqdm(range(0, len(segments), step), total=num_chunks, desc="语义场景分割 (LLM)", unit="块")

        for i in pbar:
            chunk_start = i
            chunk_end = i + self.chunk_size
            chunk = segments[chunk_start:chunk_end]

            if not chunk:
                continue

            cache_file = os.path.join(self.cache_dir, f"chunk_{chunk_start}_{chunk_end-1}.json")

            relative_split_points = []
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cached_scenes = json.load(f)
                    # 从可读的缓存中提取出分割点
                    relative_split_points = [scene['end_line_in_chunk'] for scene in cached_scenes]
                except (json.JSONDecodeError, KeyError) as e:
                    log.warning(f"缓存文件 '{os.path.basename(cache_file)}' 格式错误或已损坏: {e}。将重新生成。", exc_info=True)
                    os.remove(cache_file) # 删除损坏的缓存
                    # 让程序继续执行，以便重新生成
            
            # 如果缓存不存在或已损坏，则执行此块
            if not relative_split_points and not os.path.exists(cache_file):
                relative_split_points = self._get_split_points_from_chunk(chunk)
                
                # 为缓存构建可读的场景数据
                chunk_scenes_for_cache = self._construct_scenes_for_chunk(chunk, relative_split_points)
                
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(chunk_scenes_for_cache, f, ensure_ascii=False, indent=4)

            for point in relative_split_points:
                if 0 <= point < len(chunk):
                    absolute_index = chunk_start + point
                    all_split_indices.add(absolute_index)

        # 确保最后一个片段也被视为一个场景的结尾
        all_split_indices.add(len(segments) - 1)
        sorted_split_indices = sorted(list(all_split_indices))

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