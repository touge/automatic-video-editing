import os
import argparse
import logging
import requests
import shutil
from pydub import AudioSegment
from tqdm import tqdm
import bootstrap
from src.utils import generate_task_id, ensure_task_path
from src.logger import log
from src.tts import tts

# Suppress redundant logs from httpx
logging.getLogger("httpx").setLevel(logging.WARNING)

def download_file(url, destination):
    """Downloads a file from a URL to a destination."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except requests.exceptions.RequestException as e:
        log.error(f"Error downloading {url}: {e}")
        return False

def main(doc_file: str, task_id: str | None = None):

    log.info("--- Step 1: Set up task directory ---")
    
    if not task_id:
        task_id = generate_task_id()
        log.success(f"New task created with ID: {task_id}")
    else:
        log.info(f"Using existing task ID: {task_id}")

    if not os.path.exists(doc_file):
        log.error(f"Error: Document file not found at '{doc_file}'")
        return

    task_dir = ensure_task_path(task_id)
    
    doc_cache_dir = os.path.join(task_dir, ".documents")
    audio_cache_dir = os.path.join(task_dir, ".audios")
    doc_segments_dir = os.path.join(doc_cache_dir, "segments")
    audio_segments_dir = os.path.join(audio_cache_dir, "segments")

    os.makedirs(doc_segments_dir, exist_ok=True)
    os.makedirs(audio_segments_dir, exist_ok=True)

    log.info(f"Task directory is set up at: {task_dir}")

    log.info("Step 2: Process and segment the document")
    
    shutil.copy(doc_file, os.path.join(doc_cache_dir, "original.txt"))
    log.success("Cached original document.")

    with open(doc_file, 'r', encoding='utf-8') as f:
        content = f.read()

    segments = [seg.strip() for seg in content.split('\n\n') if seg.strip()]
    
    if not segments:
        log.error("No text segments found in the document.")
        return

    log.success(f"Document split into {len(segments)} segments.")

    for i, segment_text in enumerate(segments):
        with open(os.path.join(doc_segments_dir, f"{i}.txt"), 'w', encoding='utf-8') as f:
            f.write(segment_text)
    
    log.success("All text segments cached.")

    log.info("Step 3: Synthesize audio for each segment")

    for i, segment_text in enumerate(tqdm(segments, desc="Synthesizing Audio")):
        audio_path = os.path.join(audio_segments_dir, f"{i}.wav")
        
        try:
            response = tts.synthesize(segment_text)
            audio_url = response.get("url")
            if not audio_url:
                log.error(f"Failed to get audio URL for segment {i}.")
                continue
            
            if not download_file(audio_url, audio_path):
                log.error(f"Failed to download audio for segment {i}.")
        except Exception as e:
            log.error(f"An error occurred during synthesis for segment {i}: {e}")

    log.success("Finished synthesizing all segments.")

    log.info("Step 4: Combine all audio segments")

    audio_files = [os.path.join(audio_segments_dir, f"{i}.wav") for i in range(len(segments))]
    valid_audio_files = [f for f in audio_files if os.path.exists(f)]

    if not valid_audio_files:
        log.error("No audio files were generated to combine.")
        return
        
    if len(valid_audio_files) != len(segments):
        log.warning("Some audio segments failed to generate and will be skipped in the final audio.")

    try:
        combined_audio = AudioSegment.empty()
        for audio_file in tqdm(valid_audio_files, desc="Combining Audio"):
            segment_audio = AudioSegment.from_wav(audio_file)
            combined_audio += segment_audio
        
        final_audio_path = os.path.join(audio_cache_dir, "final_audio.wav")
        combined_audio.export(final_audio_path, format="wav")
        log.success(f"All audio segments combined successfully!")
        log.info(f"Final audio file saved to: {final_audio_path}")

    except Exception as e:
        log.error(f"Failed to combine audio files: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Step 0: Preprocess document, synthesize audio, and combine.")
    parser.add_argument("-t", "--txt-file", dest="txt_file", required=True, help="Path to the text document file.")
    parser.add_argument("-id", "--task-id", dest="task_id", required=False, default=None, help="Optional: Specify a task ID to resume or continue a task.")
    args = parser.parse_args()
    main(args.txt_file, args.task_id)
