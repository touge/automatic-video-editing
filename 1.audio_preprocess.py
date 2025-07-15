import argparse
import bootstrap
from src.logic.audio_preprocessor import AudioPreprocessor
from src.logger import log
from src.utils import generate_task_id, ensure_task_path

def main():
    parser = argparse.ArgumentParser(description="Step 0: Preprocess document, synthesize audio, and generate subtitles.")
    parser.add_argument("-t", "--txt-file", dest="txt_file", required=True, help="Path to the text document file.")
    parser.add_argument("-id", "--task-id", dest="task_id", required=False, default=None, help="Optional: Specify a task ID to resume or continue a task.")
    args = parser.parse_args()

    # --- Step 1: Task Setup ---
    log.info("--- Step 1: Setting up task directory ---")
    if not args.task_id:
        task_id = generate_task_id()
        ensure_task_path(task_id)
        args.task_id = task_id        
        log.success(f"New task created with ID: {task_id}")
    else:
        log.info(f"Using existing task ID: {task_id}")
    
    try:
        preprocessor = AudioPreprocessor(task_id=args.task_id, doc_file=args.txt_file)
        preprocessor.run()
        log.success(f"Setp 1 has been completed, Generate task id : {task_id}")
    except Exception as e:
        log.error(f"An error occurred during the preprocessing pipeline: {e}", exc_info=True)

if __name__ == "__main__":
    main()
