"""MySQL 数据库操作封装。"""

import json
import logging
import secrets
from contextlib import contextmanager
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple

import pymysql
from pymysql.cursors import DictCursor

from .config import MYSQL

logger = logging.getLogger(__name__)


class RegisterStatus(Enum):
    """服务器注册状态。"""
    PENDING = "PENDING"    # 等待管理员审核
    ACCEPTED = "ACCEPTED"  # 已接受注册
    REJECTED = "REJECTED"  # 已拒绝注册


class EventType(Enum):
    """事件类型枚举。"""
    SERVER_REGISTER = "SERVER_REGISTER"
    SERVER_ACCEPTED = "SERVER_ACCEPTED"  # 新增：注册被接受
    SERVER_REJECTED = "SERVER_REJECTED"  # 新增：注册被拒绝
    SERVER_ONLINE = "SERVER_ONLINE"
    SERVER_OFFLINE = "SERVER_OFFLINE"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    HIGH_CPU = "HIGH_CPU"
    HIGH_MEMORY = "HIGH_MEMORY"
    HIGH_DISK = "HIGH_DISK"
    HIGH_GPU = "HIGH_GPU"
    ERROR = "ERROR"


class EventSeverity(Enum):
    """事件严重程度枚举。"""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


_TABLE_SERVERS = """
CREATE TABLE IF NOT EXISTS servers (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid CHAR(36) NOT NULL UNIQUE COMMENT '客户端生成的唯一ID',
    hostname VARCHAR(255) COMMENT '主机名',
    ip_address VARCHAR(45) COMMENT '最后上报的IP',
    
    -- 服务器状态
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用监控',
    last_seen TIMESTAMP NULL COMMENT '最后一次心跳时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 配置项
    server_name VARCHAR(255) COMMENT '自定义服务器名称',
    report_interval INT DEFAULT 30 COMMENT '上报间隔(秒)',
    
    -- 监控开关
    monitor_cpu BOOLEAN DEFAULT TRUE COMMENT '是否监控CPU',
    monitor_memory BOOLEAN DEFAULT TRUE COMMENT '是否监控内存',
    monitor_disks TEXT COMMENT '需要监控的磁盘路径，逗号分隔',
    monitor_gpu BOOLEAN DEFAULT TRUE COMMENT '是否监控GPU',
    
    -- 认证相关
    auth_token VARCHAR(64) NULL COMMENT '认证Token',
    report_url VARCHAR(255) NULL COMMENT '指定的上报地址',
    register_status ENUM('PENDING', 'ACCEPTED', 'REJECTED') DEFAULT 'PENDING' COMMENT '注册状态',
    
    INDEX idx_active_seen (is_active, last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_TABLE_EVENTS = """
CREATE TABLE IF NOT EXISTS server_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    server_id BIGINT NOT NULL COMMENT '关联的服务器ID',
    event_type ENUM(
        'SERVER_REGISTER', 'SERVER_ONLINE', 'SERVER_OFFLINE',
        'CONFIG_CHANGE', 'HIGH_CPU', 'HIGH_MEMORY',
        'HIGH_DISK', 'HIGH_GPU', 'ERROR'
    ) NOT NULL COMMENT '事件类型',
    severity ENUM('INFO', 'WARNING', 'ERROR', 'CRITICAL')
        NOT NULL DEFAULT 'INFO' COMMENT '事件严重程度',
    event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '事件发生时间',
    message TEXT NOT NULL COMMENT '事件详细信息',
    extra JSON NULL COMMENT '额外信息（JSON格式）',
    
    INDEX idx_server_time (server_id, event_time),
    INDEX idx_type_time (event_type, event_time),
    CONSTRAINT fk_event_server FOREIGN KEY (server_id) REFERENCES servers(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def _get_conn():
    """获取数据库连接。"""
    return pymysql.connect(**MYSQL, autocommit=True, cursorclass=DictCursor)


@contextmanager
def get_cursor():
    """获取数据库游标的上下文管理器。"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        yield cur
    finally:
        cur.close()
        conn.close()


def init_tables():
    """确保数据库表已创建。"""
    with get_cursor() as cur:
        cur.execute(_TABLE_SERVERS)
        cur.execute(_TABLE_EVENTS)
    logger.info("数据库表初始化完成")


def register_server(uuid: str, hostname: str, ip: str) -> Dict[str, Any]:
    """处理服务器注册请求。
    
    Args:
        uuid: 客户端唯一标识
        hostname: 主机名
        ip: IP地址
    
    Returns:
        包含注册状态和配置信息的字典
    """
    with get_cursor() as cur:
        # 查询是否已存在
        cur.execute("SELECT * FROM servers WHERE uuid = %s", (uuid,))
        server = cur.fetchone()
        
        if not server:
            # 新服务器，状态为 PENDING
            cur.execute(
                """INSERT INTO servers 
                (uuid, hostname, ip_address, register_status, last_seen)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)""",
                (uuid, hostname, ip, RegisterStatus.PENDING.value)
            )
            logger.info("新服务器请求注册: %s (%s)", hostname, uuid)
            
            # 重新查询获取完整记录
            cur.execute("SELECT * FROM servers WHERE uuid = %s", (uuid,))
            server = cur.fetchone()
            
            # 记录注册事件
            add_event(
                server["id"],
                EventType.SERVER_REGISTER,
                EventSeverity.INFO,
                f"服务器请求注册: {hostname}",
                {"ip": ip},
            )
        else:
            # 已存在，更新基本信息
            cur.execute(
                """UPDATE servers 
                SET hostname = %s, ip_address = %s, last_seen = CURRENT_TIMESTAMP 
                WHERE uuid = %s""",
                (hostname, ip, uuid)
            )
            logger.info("已存在服务器更新信息: %s (%s)", hostname, uuid)
    
    # 返回状态和配置
    status = RegisterStatus(server["register_status"])
    if status == RegisterStatus.ACCEPTED:
        # 已接受的注册才返回完整配置
        return {
            "status": "accepted",
            "server_id": server["id"],
            "auth_token": server["auth_token"],
            "report_url": server["report_url"] or "http://localhost:8045/api/agent/report",
            "report_interval": server["report_interval"],
            "monitor_cpu": bool(server["monitor_cpu"]),
            "monitor_memory": bool(server["monitor_memory"]),
            "monitor_disks": server["monitor_disks"].split(",") if server["monitor_disks"] else None,
            "monitor_gpu": bool(server["monitor_gpu"]),
            "is_active": bool(server["is_active"]),
        }
    elif status == RegisterStatus.REJECTED:
        return {"status": "rejected", "message": "注册请求已被拒绝"}
    else:  # PENDING
        return {"status": "pending", "message": "注册请求正在等待审核"}


def accept_server(server_id: int) -> bool:
    """接受服务器的注册请求。
    
    Args:
        server_id: 服务器ID
    
    Returns:
        是否成功
    """
    with get_cursor() as cur:
        # 查询服务器
        cur.execute("SELECT * FROM servers WHERE id = %s", (server_id,))
        server = cur.fetchone()
        if not server:
            logger.error("服务器不存在: %d", server_id)
            return False
            
        # 生成 Token
        token = secrets.token_urlsafe(32)
        
        # 更新状态和 Token
        cur.execute(
            """UPDATE servers 
            SET register_status = %s, auth_token = %s
            WHERE id = %s""",
            (RegisterStatus.ACCEPTED.value, token, server_id)
        )
        
        # 记录事件
        add_event(
            server_id,
            EventType.SERVER_ACCEPTED,
            EventSeverity.INFO,
            f"注册请求已接受: {server['hostname']}",
        )
        
        logger.info("已接受服务器注册: %s (ID=%d)", server["hostname"], server_id)
        return True


def reject_server(server_id: int, reason: str = "") -> bool:
    """拒绝服务器的注册请求。
    
    Args:
        server_id: 服务器ID
        reason: 拒绝原因
    
    Returns:
        是否成功
    """
    with get_cursor() as cur:
        # 查询服务器
        cur.execute("SELECT * FROM servers WHERE id = %s", (server_id,))
        server = cur.fetchone()
        if not server:
            logger.error("服务器不存在: %d", server_id)
            return False
            
        # 更新状态
        cur.execute(
            "UPDATE servers SET register_status = %s WHERE id = %s",
            (RegisterStatus.REJECTED.value, server_id)
        )
        
        # 记录事件
        add_event(
            server_id,
            EventType.SERVER_REJECTED,
            EventSeverity.WARNING,
            f"注册请求已拒绝: {server['hostname']}",
            {"reason": reason} if reason else None,
        )
        
        logger.info("已拒绝服务器注册: %s (ID=%d)", server["hostname"], server_id)
        return True


def get_pending_servers() -> List[Dict[str, Any]]:
    """获取所有待审核的服务器。"""
    with get_cursor() as cur:
        cur.execute(
            """SELECT * FROM servers 
            WHERE register_status = %s
            ORDER BY created_at DESC""",
            (RegisterStatus.PENDING.value,)
        )
        return cur.fetchall()


def get_active_servers() -> List[Dict[str, Any]]:
    """获取所有已启用的服务器列表。"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM servers WHERE is_active = TRUE")
        return cur.fetchall()


def update_server_seen(uuid: str, ip: str):
    """更新服务器最后心跳时间。"""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE servers SET last_seen = CURRENT_TIMESTAMP, ip_address = %s WHERE uuid = %s",
            (ip, uuid)
        )


def add_event(
    server_id: int,
    event_type: EventType,
    severity: EventSeverity,
    message: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """添加一条服务器事件记录。
    
    Args:
        server_id: 服务器ID
        event_type: 事件类型
        severity: 严重程度
        message: 事件描述
        extra: 额外信息（将被转为JSON）
    """
    extra_json = json.dumps(extra, ensure_ascii=False) if extra else None
    
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO server_events
            (server_id, event_type, severity, message, extra)
            VALUES (%s, %s, %s, %s, %s)""",
            (server_id, event_type.value, severity.value, message, extra_json)
        )
    
    logger.info(
        "[%s] %s: %s (server_id=%d)",
        severity.value,
        event_type.value,
        message,
        server_id,
    ) 