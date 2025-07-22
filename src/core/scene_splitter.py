import os
import json
from src.logger import log
from tqdm import tqdm
import math

from src.providers.llm import LlmManager
from src.core.task_manager import TaskManager

class SceneSplitter:
    def __init__(self, config: dict, task_id: str):
        self.config = config
        self.task_manager = TaskManager(task_id)
        
        self.llm_manager = LlmManager(config)
        if not self.llm_manager.provider:
            raise ValueError("No LLM providers are available. Please check your config.yaml.")
        
        log.info("Scene splitter initialized.")

        prompts_config = self.config.get('prompts', {})
        self.prompt_template = prompts_config.get('scene_splitter')
        if not self.prompt_template:
            raise ValueError("Scene splitter prompt 'prompts.scene_splitter' not found in config.yaml")
        
        splitter_config = config.get('scene_detection', {}).get('splitter', {})
        self.chunk_size = splitter_config.get('chunk_size', 50)
        self.overlap = splitter_config.get('overlap', 10)

    def _get_split_points_from_chunk(self, chunk_segments: list) -> list[int]:
        """
        Sends a text chunk to the LLM and identifies scene change points.
        Now uses the 'generate' endpoint for efficiency and semantic correctness.
        """
        numbered_text = "\n".join([f"{i}: {seg['text']}" for i, seg in enumerate(chunk_segments)])
        prompt = self.prompt_template.format(numbered_text=numbered_text)
        try:
            # Use generate_with_failover instead of chat_with_failover
            content = self.llm_manager.generate_with_failover(
                prompt=prompt,
                temperature=0.0
            )
            raw_points = [int(n.strip()) for n in content.split(',') if n.strip().isdigit()]
            return sorted(list(set(raw_points)))
        except Exception as e:
            log.error(f"Failed to split scene: {e}. This chunk will not be split.", exc_info=True)
            return []

    def _construct_scenes_for_chunk(self, chunk_segments: list, split_points: list) -> list:
        """
        Constructs a list of scene dictionaries for a single chunk for caching.
        """
        scenes_for_cache = []
        last_split = -1
        all_points = sorted(list(set(split_points + [len(chunk_segments) - 1])))

        for point in all_points:
            start_index = last_split + 1
            end_index = point
            
            if start_index > end_index: continue
            scene_segs = chunk_segments[start_index : end_index + 1]
            if not scene_segs: continue
                
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
            log.error("chunk_size must be greater than overlap. Using default step.")
            step = self.chunk_size // 2 if self.chunk_size > 1 else 1

        num_chunks = math.ceil(len(segments) / step)
        pbar = tqdm(range(0, len(segments), step), total=num_chunks, desc="Semantic Scene Splitting (LLM)", unit="chunk")

        for i in pbar:
            chunk_start = i
            chunk_end = i + self.chunk_size
            chunk = segments[chunk_start:chunk_end]
            if not chunk: continue

            cache_file = self.task_manager.get_file_path('scene_split_chunk', start=chunk_start, end=chunk_end-1)
            relative_split_points = []

            if os.path.exists(cache_file):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        cached_scenes = json.load(f)
                    relative_split_points = [scene['end_line_in_chunk'] for scene in cached_scenes]
                except (json.JSONDecodeError, KeyError) as e:
                    log.warning(f"Cache file '{os.path.basename(cache_file)}' is corrupt: {e}. Regenerating.", exc_info=True)
                    os.remove(cache_file)
            
            if not relative_split_points and not os.path.exists(cache_file):
                relative_split_points = self._get_split_points_from_chunk(chunk)
                chunk_scenes_for_cache = self._construct_scenes_for_chunk(chunk, relative_split_points)
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(chunk_scenes_for_cache, f, ensure_ascii=False, indent=4)

            for point in relative_split_points:
                if 0 <= point < len(chunk):
                    all_split_indices.add(chunk_start + point)

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
                    "start": start_time,
                    "end": end_time,
                    "duration": round(end_time - start_time, 2),
                    "text": full_text,
                    # "segments": scene_segments
                })
            last_split = split_index

        return scenes
