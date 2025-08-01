# src/core/service_controller.py
'''
ServiceController 服务控制模块

该模块用于在任务执行过程中，统一管理第三方服务的启动、状态检测、关闭与运行状态查询。
它支持 PowerShell 启动脚本和内联命令的调用方式，并通过监听进程端口来判断服务是否正在运行。

核心功能包括：
- 自动启动服务（支持安全启动并阻塞等待）
- 服务就绪判断（可扩展关键词或接口探测）
- 自动关闭服务并清理进程
- 查询单个或全部服务的状态（用于可视化监控或健康检查）

应用场景：
- 视频处理任务、音频生成等需要依赖外部模型服务时
- 构建自动化任务调度系统
- 管理本地多模型部署或 CLI 工具调度流程

模块依赖：
- YAML:服务配置加载(services.yaml)
- subprocess/psutil:进程调度与端口监听
- Pathlib:构造相对路径

'''
import subprocess
import psutil
import yaml
import time
from pathlib import Path

class ServiceController:
    def __init__(self, config_path="services.yaml"):
        # 加载服务配置文件（YAML 格式），通常包含服务名、类型、端口等信息
        with open(config_path, encoding="utf-8") as f:
            self.services = yaml.safe_load(f)
        
        # 设置脚本根目录路径，方便构造绝对路径启动指令
        self.script_root = Path(__file__).resolve().parent.parent

        # 用于记录已启动服务的进程对象，方便后续关闭或监控状态
        self.processes = {}

    def safe_start(self, service_name: str, timeout: int = 30, interval: float = 0.5):
        """
        安全地启动一个服务并等待其就绪。
        它会自动从配置中读取 'ready_keyword'。
        """
        svc = self.services.get(service_name)
        if not svc:
            raise ValueError(f"Service '{service_name}' not defined in configuration.")
        
        keyword = svc.get("ready_keyword")
        if not keyword:
            raise ValueError(f"Service '{service_name}' in config is missing 'ready_keyword'.")

        self.start(service_name)
        try:
            self.wait_until_ready(service_name, keyword=keyword, timeout=timeout, interval=interval)
        except TimeoutError as e:
            self.stop(service_name)
            raise RuntimeError(f"[Startup Failed] Service '{service_name}' did not become ready within {timeout}s: {e}")

    def wait_until_ready(self, service_name, keyword="started", timeout=30, interval=0.1):
        """
        等待服务启动完成，通过捕获 stdout 并检查关键字来判断。
        - service_name: 正在等待的服务名
        - keyword: 用于检查就绪状态的信号关键字
        - timeout: 等待的超时时间
        - interval: 检查间隔
        """
        proc = self.processes.get(service_name)
        if not proc:
            raise RuntimeError(f"[Missing Process] Service '{service_name}' was not started or not registered.")

        # 设置 stdout 为非阻塞模式
        proc.stdout.reconfigure(encoding='utf-8', errors='ignore')
        
        start_time = time.time()
        output_buffer = ""

        while time.time() - start_time < timeout:
            # 检查进程是否意外退出
            if proc.poll() is not None:
                raise RuntimeError(f"[Startup Failed] Service '{service_name}' exited prematurely with code {proc.poll()}. Output: {output_buffer}")

            # 读取输出
            try:
                # 使用 os.read 读取非阻塞流
                line = proc.stdout.readline()
                if line:
                    print(f"[{service_name} Log]: {line.strip()}") # 实时打印日志，方便调试
                    output_buffer += line
                    if keyword in line:
                        print(f"[Ready] Service '{service_name}' is ready (keyword '{keyword}' found).")
                        self.attach_log_stream(service_name)
                        return
            except (IOError, TypeError):
                # 在非阻塞模式下，没有数据时可能会抛出异常，这是正常的
                pass

            time.sleep(interval)

        # 如果超时
        raise TimeoutError(f"[Timeout] Service '{service_name}' did not show readiness keyword '{keyword}' within {timeout}s. Last output: {output_buffer}")

    def start(self, key):
        """
        启动指定服务。如果服务有依赖项，会先递归启动依赖项。
        """
        if key not in self.services:
            print(f"[Skipped] Service '{key}' is not defined in configuration.")
            return

        svc = self.services[key]

        # 1. 启动依赖项
        if "depends_on" in svc:
            for dep_key in svc["depends_on"]:
                print(f"[Dependency] Service '{key}' depends on '{dep_key}'. Ensuring it is started safely...")
                self.safe_start(dep_key) # 使用 safe_start 确保依赖项完全就绪

        # 2. 检查服务是否已在运行
        port = svc.get("port")
        if port and self._get_pid_by_port(port):
            print(f"[Notice] Service '{key}' is already running on port {port}.")
            return

        # 3. 启动当前服务
        if svc["type"] == "ps1":
            ps1_path = str(self.script_root / svc["path"])
            cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", ps1_path, "-Port", str(port)]
        elif svc["type"] == "cmd":
            cmd = ["powershell", "-Command", svc["command"]]
        else:
            print(f"[Error] Unknown service type: {svc['type']}")
            return

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore')
        self.processes[key] = proc
        print(f"[Started] Service '{svc['name']}' with PID {proc.pid}")

    def stop(self, key):
        """
        停止指定服务。如果服务有依赖项，会一并停止。
        """
        svc = self.services.get(key)
        if not svc:
            print(f"[Skipped] Service '{key}' is not defined in configuration.")
            return

        # 1. 停止当前服务
        port = svc.get("port")
        if port:
            # 1.1 执行优雅关闭命令
            if "stop_command" in svc:
                stop_cmd = svc["stop_command"]
                print(f"[Graceful Stop] Executing stop command for '{key}': {stop_cmd}")
                try:
                    subprocess.run(stop_cmd, shell=True, check=True, capture_output=True, text=True)
                    print(f"[Graceful Stop] Successfully executed stop command for '{key}'.")
                    time.sleep(2) # 等待命令生效
                except Exception as e:
                    print(f"[Graceful Stop] Warning: Stop command for '{key}' failed: {e}")

            # 1.2 强制终止进程
            pid = self._get_pid_by_port(port)
            if pid:
                try:
                    process = psutil.Process(pid)
                    process.terminate()
                    process.wait(timeout=5)
                    print(f"[Stopped] Service '{svc['name']}' with PID {pid}")
                except psutil.NoSuchProcess:
                    print(f"[Notice] Process with PID {pid} no longer exists for '{key}'.")
                except psutil.TimeoutExpired:
                    print(f"[Warning] Process {pid} for '{key}' did not terminate gracefully, forcing kill.")
                    process.kill()
                except Exception as e:
                    print(f"[Error] Failed to terminate PID {pid} for '{key}': {e}")
            else:
                 if "stop_command" not in svc:
                    print(f"[Notice] No process found for service '{key}' on port {port}")
        
        # 2. 停止依赖项
        if "depends_on" in svc:
            for dep_key in svc["depends_on"]:
                print(f"[Dependency] Stopping dependency '{dep_key}' for service '{key}'...")
                self.stop(dep_key) # 递归停止

    def status(self, key: str) -> dict:
        """
        查询单个服务的运行状态，包括端口、PID、是否运行中。
        返回格式：
        {
            "name": 服务名称,
            "port": 使用的端口,
            "pid": 正在监听端口的进程 ID,
            "running": 是否正在运行,
            "reason": （若未找到服务）原因描述
        }
        """
        service = self.services.get(key)
        if not service:
            return {
                "name": key,
                "port": None,
                "pid": None,
                "running": False,
                "reason": "Service not found in configuration"
            }

        port = service.get("port")
        pid = self._get_pid_by_port(port)

        return {
            "name": key,
            "port": port,
            "pid": pid,
            "running": bool(pid)
        }

    def status_all(self) -> list[dict]:
        """
        获取所有服务的状态信息列表，适用于批量展示和健康检查。
        """
        statuses = []
        for key in self.services.keys():
            status = self.status(key)
            statuses.append(status)
        return statuses

    def _get_pid_by_port(self, port: int) -> int | None:
        """
        查找指定端口的监听进程 PID（用于服务关闭、状态判断）
        """
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                return conn.pid
        return None

    def attach_log_stream(self, service_name: str):
        """
        持续监听服务运行期输出并打印，适用于实时观察任务过程。
        """
        proc = self.processes.get(service_name)
        if not proc:
            raise ValueError(f"No running process for '{service_name}'")

        def stream():
            while True:
                if proc.poll() is not None:
                    print(f"[LogStream] Service '{service_name}' has exited.")
                    break
                line = proc.stdout.readline()
                if line:
                    print(f"[{service_name} Runtime]: {line.strip()}")

        import threading
        threading.Thread(target=stream, daemon=True).start()
