import argparse
import bootstrap
from src.logic.video_composer_logic import VideoComposition
from src.utils import check_llm_providers
from src.config_loader import config
from src.logger import log

def main():
    parser = argparse.ArgumentParser(description="Step 3: Compose the final video from scenes, assets, audio, and subtitles.")
    parser.add_argument("-id", "--task-id", dest="task_id", required=True, help="The ID of the task to process.")
    parser.add_argument("--burn-subtitle", action="store_true", help="Whether to generate subtitles for the video.")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with verbose logging")
    args = parser.parse_args()

    # AssetManager might use an LLM for keyword generation, so we check providers.
    check_llm_providers(config)

    # 设置调试模式
    if args.debug:
        import logging
        log.setLevel(logging.DEBUG)
        log.debug("调试模式已启用")

    try:
        # 从配置中获取场景配置，如果不存在则默认为空字典
        scene_config = config.get('composition_settings', {}).get('scene_config', {})
        composer = VideoComposition(task_id=args.task_id, burn_subtitle=args.burn_subtitle, scene_config=scene_config)
        composer.run()
    except Exception as e:
        log.error(f"视频合成过程中发生错误: {str(e)}", exc_info=True)
        # 打印更多上下文信息
        if hasattr(e, '__context__'):
            log.error(f"错误上下文: {str(e.__context__)}")

if __name__ == "__main__":
    main()
