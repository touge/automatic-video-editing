import logging
from rich.logging import RichHandler

# 配置一个全局的、带颜色的日志记录器
# rich_tracebacks=True: 当发生异常时，提供美观且详细的回溯信息
# tracebacks_show_locals=False: 为安全起见，不在异常回溯中显示局部变量
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, tracebacks_show_locals=False, show_path=False)]
)

# 获取一个可以全局使用的logger实例
log = logging.getLogger("rich")