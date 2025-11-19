"""心跳管理模块，负责在非监控状态下维持与服务端的连接。"""

import logging
import socket
import time
from typing import Dict, Any, Optional

from .identity import get_client_id
from .config import is_server_active, is_monitoring_enabled

logger = logging.getLogger(__name__)


class HeartbeatManager:
    """心跳管理器，负责在非监控状态下发送心跳包"""
    
    def __init__(self, sender, monitor_config):
        """初始化心跳管理器
        
        Args:
            sender: 数据发送器实例
            monitor_config: 监控配置管理器实例
        """
        self.sender = sender
        self.monitor_config = monitor_config
        self.last_heartbeat_time = 0
        self.heartbeat_count = 0
    
    def should_send_heartbeat(self) -> tuple[bool, str]:
        """检查是否应该发送心跳包
        
        Returns:
            tuple: (是否发送心跳包, 心跳原因)
        """
        # 检查服务器是否启用监控
        if not is_server_active():
            return True, "服务器已禁用监控"
        
        # 检查是否有任何监控项被启用
        if not is_monitoring_enabled():
            return True, "所有监控项均已禁用"
        
        # 检查是否在监控时间内
        if not self.monitor_config.is_monitoring_time():
            return True, "当前时间不在监控范围内"
        
        return False, ""
    
    def create_heartbeat_data(self, reason: str) -> Dict[str, Any]:
        """创建心跳包数据
        
        Args:
            reason: 发送心跳的原因
            
        Returns:
            Dict: 心跳包数据
        """
        self.heartbeat_count += 1
        
        heartbeat_data = {
            "timestamp": int(time.time()),
            "client_id": get_client_id(),
            "hostname": socket.gethostname(),
            "heartbeat": True,  # 标识这是心跳包
            "heartbeat_sequence": self.heartbeat_count,  # 心跳序号
            "reason": reason,  # 心跳原因
            "monitor_status": self.monitor_config.get_status_info(),  # 监控状态信息
            "server_active": is_server_active(),  # 服务器状态
            "monitoring_enabled": is_monitoring_enabled(),  # 监控项启用状态
            "last_heartbeat_time": self.last_heartbeat_time  # 上次心跳时间
        }
        
        return heartbeat_data
    
    def send_heartbeat(self, reason: str) -> bool:
        """发送心跳包
        
        Args:
            reason: 发送心跳的原因
            
        Returns:
            bool: 是否发送成功
        """
        try:
            heartbeat_data = self.create_heartbeat_data(reason)
            
            # 直接发送心跳包，不经过缓存
            success = self.sender.send_immediate(heartbeat_data)
            
            if success:
                self.last_heartbeat_time = int(time.time())
                logger.info("心跳包发送成功 (序号: %d, 原因: %s)", 
                           self.heartbeat_count, reason)
                return True
            else:
                logger.warning("心跳包发送失败 (序号: %d, 原因: %s)", 
                              self.heartbeat_count, reason)
                return False
                
        except Exception as e:
            logger.error("发送心跳包时发生异常: %s", e)
            return False
    
    def get_heartbeat_stats(self) -> Dict[str, Any]:
        """获取心跳统计信息
        
        Returns:
            Dict: 心跳统计信息
        """
        return {
            "total_heartbeats": self.heartbeat_count,
            "last_heartbeat_time": self.last_heartbeat_time,
            "current_time": int(time.time()),
            "time_since_last_heartbeat": int(time.time()) - self.last_heartbeat_time if self.last_heartbeat_time > 0 else 0
        }


def create_minimal_heartbeat(reason: str = "keep_alive") -> Dict[str, Any]:
    """创建最小化的心跳包（用于紧急情况）
    
    Args:
        reason: 心跳原因
        
    Returns:
        Dict: 最小化心跳包数据
    """
    return {
        "timestamp": int(time.time()),
        "client_id": get_client_id(),
        "hostname": socket.gethostname(),
        "heartbeat": True,
        "reason": reason,
        "minimal": True  # 标识这是最小化心跳包
    }


def should_force_heartbeat(last_activity_time: int, max_silence_duration: int = 300) -> bool:
    """检查是否应该强制发送心跳包（防止长时间静默）
    
    Args:
        last_activity_time: 上次活动时间
        max_silence_duration: 最大静默时长（秒），默认5分钟
        
    Returns:
        bool: 是否应该强制发送心跳包
    """
    current_time = int(time.time())
    silence_duration = current_time - last_activity_time
    
    if silence_duration >= max_silence_duration:
        logger.info("检测到长时间静默 (%d秒)，需要发送强制心跳包", silence_duration)
        return True
    
    return False
