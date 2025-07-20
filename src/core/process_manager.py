import psutil
import os
import signal
from typing import Set
from src.logger import log

# --- 中文注释 ---
# 这是一个全局的进程管理器，用于跟踪和终结由本应用启动的所有子进程。
# 它的主要目的是解决当用户按下 Ctrl+C 时，由 subprocess.Popen 启动的
# 外部进程（如 ffmpeg）不会自动退出，从而导致主程序卡住的问题。

class ProcessManager:
    """
    一个单例（Singleton）类，用于在整个应用程序生命周期内管理子进程。
    """
    _instance = None
    # 使用一个集合来存储所有被跟踪的子进程对象（psutil.Process）
    _child_processes: Set[psutil.Process] = set()

    # 实现单例模式，确保全局只有一个 ProcessManager 实例
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ProcessManager, cls).__new__(cls)
        return cls._instance

    def register_process(self, pid: int):
        """
        根据进程ID（PID）注册一个新的子进程以进行跟踪。
        :param pid: 新创建的子进程的 PID。
        """
        try:
            process = psutil.Process(pid)
            self._child_processes.add(process)
            log.debug(f"已注册新的子进程，PID: {pid}")
        except psutil.NoSuchProcess:
            log.warning(f"尝试注册 PID 为 {pid} 的进程，但它已经退出。")

    def terminate_all_processes(self):
        """
        优雅地终止所有被跟踪的子进程。
        首先尝试发送 SIGTERM 信号，如果进程在超时后仍未退出，则强制发送 SIGKILL 信号。
        """
        log.info("正在终止所有子进程...")
        # 创建一个当前进程列表的副本进行迭代，因为集合在迭代时不能被修改
        for process in list(self._child_processes):
            try:
                # 首先终止所有孙子进程
                for child in process.children(recursive=True):
                    log.debug(f"正在终止孙子进程 {child.pid}...")
                    child.terminate()
                
                # 然后终止主子进程
                log.debug(f"正在终止子进程 {process.pid}...")
                process.terminate()
            except psutil.NoSuchProcess:
                # 如果进程已经不存在，说明它已经自行退出了
                pass
        
        # 等待最多3秒，让进程有机会自行清理和退出
        gone, alive = psutil.wait_procs(self._child_processes, timeout=3)
        
        # 对任何仍在运行的“顽固”进程，进行强制杀死
        for process in alive:
            try:
                log.warning(f"进程 {process.pid} 未能优雅退出，正在强制终止。")
                process.kill()
            except psutil.NoSuchProcess:
                pass
        
        # 清空已跟踪的进程集合
        self._child_processes.clear()
        log.info("所有子进程均已终止。")

# 创建 ProcessManager 的全局唯一实例，供应用各处使用
process_manager = ProcessManager()

def setup_signal_handlers():
    """
    设置全局信号处理器，以捕获退出信号（如 Ctrl+C）。
    """
    def handle_exit(signum, frame):
        """
        这是一个信号处理函数。当接收到指定的信号时，它会被调用。
        """
        log.warning(f"接收到信号 {signum}。正在启动优雅关闭程序...")
        # 调用进程管理器来清理所有子进程
        process_manager.terminate_all_processes()
        # 使用 os._exit(1) 强制退出主程序，避免进入其他可能卡住的清理逻辑
        os._exit(1)

    # 将 SIGINT (通常由 Ctrl+C 触发) 和 SIGTERM (标准的终止信号) 绑定到我们的处理函数上
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)
    log.info("已设置信号处理器，以实现优雅关闭。")
