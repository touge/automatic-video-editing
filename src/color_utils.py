# color_utils.py
from colorama import init, Fore, Back, Style

# 初始化 Colorama，autoreset=True 可在每次 print 后自动重置样式
init(autoreset=True)

# 可选颜色和风格映射
_FORE_COLORS = {
    "BLACK":   Fore.BLACK,
    "RED":     Fore.RED,
    "GREEN":   Fore.GREEN,
    "YELLOW":  Fore.YELLOW,
    "BLUE":    Fore.BLUE,
    "MAGENTA": Fore.MAGENTA,
    "CYAN":    Fore.CYAN,
    "WHITE":   Fore.WHITE,
}

_BACK_COLORS = {
    "BLACK":   Back.BLACK,
    "RED":     Back.RED,
    "GREEN":   Back.GREEN,
    "YELLOW":  Back.YELLOW,
    "BLUE":    Back.BLUE,
    "MAGENTA": Back.MAGENTA,
    "CYAN":    Back.CYAN,
    "WHITE":   Back.WHITE,
}

_STYLES = {
    "DIM":       Style.DIM,
    "NORMAL":    Style.NORMAL,
    "BRIGHT":    Style.BRIGHT,
}

def print_colored(
    text: str,
    fg: str = "WHITE",
    bg: str | None = None,
    style: str = "NORMAL"
) -> None:
    """
    在终端打印带颜色和风格的文本。

    参数:
      text: 要打印的文本
      fg: 前景色名称 (BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE)
      bg: 背景色名称，可选 (同前景色名称)
      style: 文本风格 ("DIM", "NORMAL", "BRIGHT")
    """
    fore_code = _FORE_COLORS.get(fg.upper(), "")
    back_code = _BACK_COLORS.get(bg.upper(), "") if bg else ""
    style_code = _STYLES.get(style.upper(), "")
    print(f"{style_code}{fore_code}{back_code}{text}")

# 一些常用快捷方法
def print_error(msg: str) -> None:
    print_colored(msg, fg="RED", style="BRIGHT")

def print_warning(msg: str) -> None:
    print_colored(msg, fg="YELLOW", style="BRIGHT")

def print_success(msg: str) -> None:
    print_colored(msg, fg="GREEN", style="BRIGHT")

def print_info(msg: str) -> None:
    print_colored(msg, fg="CYAN", style="NORMAL")
