import argparse
import bootstrap
from src.logic.scene_generator import SceneGenerator
from src.utils import check_llm_providers
from src.config_loader import config
from src.logger import log

def main():
    parser = argparse.ArgumentParser(description="Step 1: Analyze subtitles and split them into scenes.")
    parser.add_argument("-id", "--task-id", dest="task_id", required=True, help="The ID of the task to process.")
    args = parser.parse_args()

    # Perform a check of the LLM providers before starting
    check_llm_providers(config)

    try:
        generator = SceneGenerator(task_id=args.task_id)
        generator.run()
        log.success(f"Step 2 has been completed for task: {args.task_id}")
    except Exception as e:
        log.error(f"An error occurred during scene generation: {e}", exc_info=True)

if __name__ == "__main__":
    main()
