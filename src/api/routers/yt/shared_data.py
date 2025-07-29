from typing import Dict, Any

# 简单的内存任务存储，供所有 yt 相关的路由共享
# 实际生产环境可能需要 Redis, 数据库或其他持久化存储
tasks: Dict[str, Dict[str, Any]] = {}
