import logging
from rich.logging import RichHandler
from rich.text import Text
from typing import Optional

# 1. 定义自定义日志级别
SUCCESS_LEVEL_NUM = 25
logging.addLevelName(SUCCESS_LEVEL_NUM, "SUCCESS")

class CustomLogger(logging.Logger):
    def success(self, message, *args, **kws):
        if self.isEnabledFor(SUCCESS_LEVEL_NUM):
            self._log(SUCCESS_LEVEL_NUM, message, args, **kws)

logging.setLoggerClass(CustomLogger)

# 2. 创建一个自定义的 RichHandler 来控制颜色
class CustomRichHandler(RichHandler):
    def get_level_emoji(self, record: logging.LogRecord) -> Optional[Text]:
        # 如果需要，可以在这里为不同级别添加表情符号
        return None

    def render_message(self, record: logging.LogRecord, message: str) -> "ConsoleRenderable":
        """
        通过重写此方法来根据日志级别渲染消息样式。
        """
        if record.levelno == SUCCESS_LEVEL_NUM:
            return Text(message, style="bold green")
        # 对于其他级别，可以保持默认行为或自定义
        return super().render_message(record, message)

# 3. 配置我们的自定义 Handler
handler = CustomRichHandler(
    rich_tracebacks=True,
    tracebacks_show_locals=False,
    show_path=False,
    show_level=True, # 显示级别名称，以便样式生效
    show_time=True,
)

# 4. 创建并配置我们的自定义 logger
log = CustomLogger("rich")
log.setLevel(logging.INFO)
log.addHandler(handler)
log.propagate = False # 防止消息被传递给根 logger，避免重复输出

# 5. 根据 config.yaml 配置 API 服务器的调试模式
try:
    from src.config_loader import config
    api_server_config = config.get('api_server', {})
    api_debug_mode = api_server_config.get('debug_mode', False)

    if not api_debug_mode:
        # 如果不是调试模式，屏蔽 asyncio 的 INFO 级别日志，以减少底层网络噪音
        logging.getLogger('asyncio').setLevel(logging.WARNING)
        # Uvicorn 的 access 和 error 日志通常是重要的，不应轻易屏蔽
        # logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
        # logging.getLogger('uvicorn.error').setLevel(logging.WARNING)
        log.info("API服务器底层网络错误日志已屏蔽 (非调试模式)。")
    else:
        log.info("API服务器底层网络错误日志已启用 (调试模式)。")

except ImportError:
    log.warning("无法导入 config_loader，API服务器调试模式配置将跳过。")
except Exception as e:
    log.error(f"加载 API 服务器调试模式配置时出错: {e}")


if __name__ == '__main__':
    log.info("This is an info message.")
    log.success("This is a success message!")
    log.warning("This is a warning message.")
    log.error("This is an error message.")
    try:
        1 / 0
    except ZeroDivisionError:
        log.exception("An exception occurred.")
