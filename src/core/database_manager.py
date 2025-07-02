import sqlite3
import os
from typing import List, Set
from pathlib import Path

DB_PATH = Path("storage") / "asset_library.db"

class DatabaseManager:
    """
    管理本地素材的SQLite数据库。
    """
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH)
        self.setup_database()

    def setup_database(self):
        """创建数据库表结构（如果不存在）。"""
        cursor = self.conn.cursor()
        # 简单的schema：将关键词存储为用空格分隔的字符串，便于用LIKE搜索。
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                keywords TEXT,
                file_path TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 为source和source_id创建唯一索引，防止重复记录，并加速查找。
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_source ON assets (asset_source, source_id);
        """)
        self.conn.commit()

    def add_asset(self, asset_source: str, source_id: str, keywords: List[str], file_path: str) -> bool:
        """向数据库添加一条新的素材记录。"""
        # 将关键词列表规范化为一个可搜索的字符串
        keywords_str = " ".join(sorted(list(set(kw.lower() for kw in keywords))))
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO assets (asset_source, source_id, keywords, file_path) VALUES (?, ?, ? ,?)",
                    (asset_source, source_id, keywords_str, file_path)
                )
            return True
        except sqlite3.IntegrityError:
            # 如果记录已存在（UNIQUE约束失败），则忽略。
            return False

    def find_asset_by_source_id(self, asset_source: str, source_id: str) -> str | None:
        """通过来源和来源ID精确查找素材路径。"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT file_path FROM assets WHERE asset_source = ? AND source_id = ?", (asset_source, source_id))
        result = cursor.fetchone()
        # 如果找到了记录，但文件在磁盘上已被删除，则返回None
        if result and Path(result[0]).exists():
            return result[0]
        return None

    def find_assets_by_keywords(self, keywords: List[str], limit: int) -> List[str]:
        """
        通过关键词在数据库中搜索素材，并根据匹配度排序。
        匹配最多关键词的素材会排在最前面。
        """
        if not keywords:
            return []

        # 动态构建查询
        # WHERE子句：匹配任何一个关键词
        where_clauses = " OR ".join(["keywords LIKE ?"] * len(keywords))
        # ORDER BY子句：计算匹配了多少个关键词，并按此降序排序
        order_by_clauses = " + ".join(["(CASE WHEN keywords LIKE ? THEN 1 ELSE 0 END)"] * len(keywords))

        # 查询参数。每个关键词在WHERE和ORDER BY中都用了一次。
        params = [f"%{kw.lower()}%" for kw in keywords] * 2

        # 最终查询语句，限制返回数量
        query = f"""
            SELECT file_path, ({order_by_clauses}) as match_score
            FROM assets
            WHERE {where_clauses}
            ORDER BY match_score DESC
            LIMIT ?
        """
        params.append(limit)

        cursor = self.conn.cursor()
        cursor.execute(query, tuple(params))

        # 过滤掉磁盘上不存在的文件
        valid_paths = [row[0] for row in cursor.fetchall() if Path(row[0]).exists()]
        return valid_paths

    def __del__(self):
        if self.conn:
            self.conn.close()