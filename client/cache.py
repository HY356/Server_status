"""SQLite 本地缓存实现，用于离线保存 24 小时内的采集数据。"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

import logging

logger = logging.getLogger(__name__)

_SQL_INIT = """
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    data TEXT NOT NULL,
    sent INTEGER DEFAULT 0
);
"""


class Cache:
    """简易 SQLite 缓存封装。线程安全需求不高，这里每次操作持久化连接。"""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._ensure_db()

    # ------------------------------ 私有方法 ------------------------------
    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)

    def _ensure_db(self) -> None:
        conn = self._get_conn()
        try:
            conn.execute(_SQL_INIT)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------ 对外接口 ------------------------------
    def save(self, data: Dict[str, Any]) -> None:
        """插入一条新的 metrics 记录。"""
        ts = int(time.time())
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO metrics (timestamp, data, sent) VALUES (?, ?, 0)",
                (ts, json.dumps(data)),
            )
            conn.commit()
        finally:
            conn.close()

    def get_unsent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取尚未成功发送到服务端的记录。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT id, timestamp, data FROM metrics WHERE sent = 0 ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "data": json.loads(row[2]),
                }
                for row in rows
            ]
        finally:
            conn.close()

    def mark_sent(self, ids: List[int]) -> None:
        """批量标记指定记录为已发送。"""
        if not ids:
            return
        conn = self._get_conn()
        try:
            conn.executemany("UPDATE metrics SET sent = 1 WHERE id = ?", [(i,) for i in ids])
            conn.commit()
        finally:
            conn.close()

    def prune(self, max_age_seconds: int) -> None:
        """删除早于 *max_age_seconds* 的数据行。"""
        threshold = int(time.time()) - max_age_seconds
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM metrics WHERE timestamp < ?", (threshold,))
            conn.commit()
        finally:
            conn.close() 