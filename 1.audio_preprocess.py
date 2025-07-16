import argparse
import bootstrap
from src.logic.audio_preprocessor import AudioPreprocessor
from src.logger import log
from src.core.task_manager import TaskManager
from src.tts import tts

def main():
    # --- Step 0: Check for TTS availability before anything else ---
    log.info("--- Checking TTS provider availability ---")
    if not tts.manager.check_availability():
        log.error("TTS service is not available. Please check your configuration and network. Aborting.")
        return

    parser = argparse.ArgumentParser(description="Step 0: Preprocess document, synthesize audio, and generate subtitles.")
    parser.add_argument("-t", "--txt-file", dest="txt_file", required=True, help="Path to the text document file.")
    parser.add_argument("-id", "--task-id", dest="task_id", required=False, default=None, help="Optional: Specify a task ID to resume or continue a task.")
    args = parser.parse_args()

    # --- Step 1: Task Setup ---
    task_manager = TaskManager(args.task_id)
    if task_manager.is_new:
        log.success(f"New task created with ID: {task_manager.task_id}")
    else:
        log.info(f"Using existing task ID: {task_manager.task_id}")

    try:
        preprocessor = AudioPreprocessor(task_id=task_manager.task_id, doc_file=args.txt_file)
        preprocessor.run()
        log.success(f"Step 1 has been completed for task: {task_manager.task_id}")
    except Exception as e:
        log.error(f"An error occurred during the preprocessing pipeline: {e}", exc_info=True)

if __name__ == "__main__":
    main()
