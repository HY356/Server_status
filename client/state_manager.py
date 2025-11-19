"""客户端状态管理模块，处理删除检测和状态切换。"""

import logging
import os
import time
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any
import requests

from .config import REGISTER_URL
from .timing_config import HTTP_TIMEOUT
from .identity import get_client_id, get_auth_token, get_os_info

logger = logging.getLogger(__name__)


class ClientState(Enum):
    """客户端状态枚举"""
    UNREGISTERED = "unregistered"    # 未注册
    REGISTERING = "registering"      # 注册中
    REGISTERED = "registered"        # 已注册
    DELETED = "deleted"              # 已删除（触发重新初始化）
    REINITIALIZED = "reinitialized"  # 已重新初始化（等待重注册）
    SLEEP_RETRY = "sleep_retry"      # 休眠重注册模式
    ERROR = "error"                  # 错误状态


class StateManager:
    """客户端状态管理器"""
    
    def __init__(self):
        self.state = ClientState.UNREGISTERED
        self.state_file = Path("client_state.json")
        self.delete_marker_file = Path(".client_delete_marker")
        self.error_start_time = 0  # 错误状态开始时间
        self.error_retry_count = 0  # 错误状态重试次数
        self._load_state()
    
    def _load_state(self) -> None:
        """从文件加载状态"""
        try:
            if self.state_file.exists():
                import json
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    state_str = data.get("state", "unregistered")
                    loaded_state = ClientState(state_str)

                    # 启动时自动重置某些临时状态（可配置）
                    should_reset = False
                    reset_reason = ""

                    if loaded_state == ClientState.ERROR:
                        from .config import AUTO_RESET_ERROR_STATE_ON_STARTUP
                        if AUTO_RESET_ERROR_STATE_ON_STARTUP:
                            should_reset = True
                            reset_reason = "错误状态"

                    elif loaded_state == ClientState.REGISTERING:
                        from .config import AUTO_RESET_REGISTERING_STATE_ON_STARTUP
                        if AUTO_RESET_REGISTERING_STATE_ON_STARTUP:
                            should_reset = True
                            reset_reason = "注册中状态"

                    if should_reset:
                        logger.info("检测到%s，重启时自动重置为未注册状态", reset_reason)
                        self.state = ClientState.UNREGISTERED
                        # 重置错误相关计数
                        self.error_start_time = 0
                        self.error_retry_count = 0
                        # 立即保存新状态
                        self._save_state()
                    else:
                        self.state = loaded_state
                        logger.info("加载客户端状态: %s", self.state.value)
            else:
                self.state = ClientState.UNREGISTERED
                logger.info("初始化客户端状态: %s", self.state.value)
        except Exception as e:
            logger.error("加载状态失败: %s", e)
            self.state = ClientState.UNREGISTERED
    
    def _save_state(self) -> None:
        """保存状态到文件"""
        try:
            import json
            data = {
                "state": self.state.value,
                "timestamp": int(time.time())
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f)
            logger.debug("保存客户端状态: %s", self.state.value)
        except Exception as e:
            logger.error("保存状态失败: %s", e)
    
    def set_state(self, new_state: ClientState) -> None:
        """设置新状态"""
        if self.state != new_state:
            old_state = self.state
            self.state = new_state

            # 处理错误状态的特殊逻辑
            if new_state == ClientState.ERROR:
                if old_state != ClientState.ERROR:
                    # 首次进入错误状态
                    self.error_start_time = int(time.time())
                    self.error_retry_count = 0
                    logger.info("进入错误状态，开始错误恢复计时")
                else:
                    # 已经在错误状态，增加重试计数
                    self.error_retry_count += 1
            else:
                # 离开错误状态，重置错误相关计数
                if old_state == ClientState.ERROR:
                    logger.info("离开错误状态，重置错误计数")
                    self.error_start_time = 0
                    self.error_retry_count = 0

            self._save_state()
            logger.info("状态变更: %s -> %s", old_state.value, new_state.value)
    
    def get_state(self) -> ClientState:
        """获取当前状态"""
        return self.state
    
    def check_delete_marker(self) -> bool:
        """检查删除标记文件是否存在"""
        return self.delete_marker_file.exists()
    
    def create_delete_marker(self) -> None:
        """创建删除标记文件"""
        try:
            self.delete_marker_file.write_text(f"deleted_at_{int(time.time())}")
            logger.info("创建删除标记文件")
        except Exception as e:
            logger.error("创建删除标记文件失败: %s", e)
    
    def remove_delete_marker(self) -> None:
        """移除删除标记文件"""
        try:
            if self.delete_marker_file.exists():
                self.delete_marker_file.unlink()
                logger.info("移除删除标记文件")
        except Exception as e:
            logger.error("移除删除标记文件失败: %s", e)
    
    def notify_server_deletion(self) -> bool:
        """通知服务端设备已删除"""
        try:
            import socket
            client_id = get_client_id()
            token = get_auth_token()
            os_info = get_os_info()

            payload = {
                "client_id": client_id,
                "hostname": socket.gethostname(),
                "os": os_info,
                "action": "delete",
                "timestamp": int(time.time())
            }
            
            headers = {
                "X-Auth-Token": token,
                "Content-Type": "application/json"
            }
            
            # 使用注册URL的删除端点（需要服务端支持）
            delete_url = REGISTER_URL.replace("/register", "/delete")
            
            resp = requests.post(delete_url, json=payload, timeout=HTTP_TIMEOUT, headers=headers)
            
            if resp.status_code == 200:
                logger.info("成功通知服务端设备删除")
                return True
            else:
                logger.error("通知服务端删除失败: %s", resp.text)
                return False
                
        except Exception as e:
            logger.error("通知服务端删除时发生异常: %s", e)
            return False
    
    def reset_client(self) -> None:
        """重置客户端状态，准备重新注册"""
        try:
            # 删除状态文件
            if self.state_file.exists():
                self.state_file.unlink()
            
            # 删除客户端ID文件，强制重新生成
            client_id_file = Path("client_id.txt")
            if client_id_file.exists():
                client_id_file.unlink()
            
            # 删除缓存数据库
            cache_db = Path("client_cache.db")
            if cache_db.exists():
                cache_db.unlink()
            
            # 移除删除标记
            self.remove_delete_marker()
            
            # 重置状态
            self.state = ClientState.UNREGISTERED
            
            logger.info("客户端状态已重置，准备重新注册")
            
        except Exception as e:
            logger.error("重置客户端状态失败: %s", e)
    
    def should_enter_sleep_retry_mode(self) -> bool:
        """检查是否应该进入休眠重注册模式"""
        return self.state in [ClientState.REINITIALIZED, ClientState.SLEEP_RETRY]

    def enter_sleep_retry_mode(self) -> None:
        """进入休眠重注册模式"""
        logger.info("进入休眠重注册模式")
        self.set_state(ClientState.SLEEP_RETRY)

    def sleep_and_retry_register(self, retry_count: int = 0) -> bool:
        """休眠并重试注册（智能间隔）"""
        import time
        from .timing_config import get_sleep_retry_interval

        # 使用配置文件中的智能休眠间隔
        sleep_interval = get_sleep_retry_interval(retry_count)

        if sleep_interval > 0:
            logger.info("休眠重注册模式：等待 %d 分钟后重试注册 (第%d次重试)", sleep_interval // 60, retry_count + 1)
            try:
                time.sleep(sleep_interval)
                logger.info("休眠结束，准备重试注册")
            except KeyboardInterrupt:
                logger.info("用户中断休眠，退出程序")
                return False
        else:
            logger.info("立即重试注册 (第%d次重试)", retry_count + 1)

        return True

    def handle_register_response(self, response_data: dict) -> str:
        """处理注册响应，返回下一步操作"""
        status = response_data.get("status", "unknown")

        if status == "pending":
            logger.info("注册状态: pending，继续休眠重试")
            return "continue_sleep"

        elif status == "accepted":
            logger.info("注册成功，退出休眠模式，恢复正常运行")
            self.set_state(ClientState.REGISTERED)
            self._record_reactivation()
            return "resume_normal"

        elif status == "rejected":
            logger.info("注册被拒绝，继续休眠重试")
            return "continue_sleep"

        elif status == "deleted":
            logger.warning("注册时再次收到删除状态，重新执行初始化流程")
            self.reinitialize_device()
            return "reinitialize"

        else:
            logger.warning("未知注册状态: %s，继续休眠重试", status)
            return "continue_sleep"

    def _record_reactivation(self) -> None:
        """记录重新激活日志"""
        import time

        try:
            reactivation_data = {
                "reactivation_timestamp": int(time.time()),
                "previous_reinit_count": self._get_reinit_count()
            }

            import json
            reactivation_file = Path("reactivation_info.json")
            with open(reactivation_file, 'w') as f:
                json.dump(reactivation_data, f)

            logger.info("设备重新激活成功，恢复正常运行")

        except Exception as e:
            logger.error("记录重新激活信息失败: %s", e)

    def should_stop_registration(self) -> bool:
        """检查是否应该停止注册过程"""
        # 检查是否应该从错误状态自动恢复
        if self.state == ClientState.ERROR:
            return not self._should_auto_recover_from_error()

        # DELETED状态会触发重新初始化，不会停止注册
        return False

    def _should_auto_recover_from_error(self) -> bool:
        """检查是否应该从错误状态自动恢复"""
        if self.state != ClientState.ERROR:
            return False

        current_time = int(time.time())
        error_duration = current_time - self.error_start_time

        # 错误状态超过5分钟，自动尝试恢复
        MAX_ERROR_DURATION = 300  # 5分钟
        if error_duration >= MAX_ERROR_DURATION:
            logger.info("错误状态持续 %d 秒，尝试自动恢复", error_duration)
            self._attempt_error_recovery()
            return True

        # 错误重试次数超过10次，尝试重置
        MAX_ERROR_RETRIES = 10
        if self.error_retry_count >= MAX_ERROR_RETRIES:
            logger.info("错误重试次数达到 %d 次，尝试重置状态", self.error_retry_count)
            self._attempt_error_recovery()
            return True

        return False

    def _attempt_error_recovery(self) -> None:
        """尝试从错误状态恢复"""
        try:
            logger.info("开始错误状态自动恢复...")

            # 检查是否有删除标记文件
            if self.check_delete_marker():
                logger.info("发现删除标记文件，执行重新初始化")
                self.reinitialize_device()
                return

            # 尝试重置为未注册状态，重新开始注册流程
            logger.info("重置为未注册状态，重新开始注册流程")
            self.set_state(ClientState.UNREGISTERED)

        except Exception as e:
            logger.error("错误状态自动恢复失败: %s", e)
            # 如果恢复失败，延长错误状态时间，避免频繁重试
            self.error_start_time = int(time.time())

    def should_stop_reporting(self) -> bool:
        """检查是否应该停止上报"""
        # 检查是否应该从错误状态自动恢复
        if self.state == ClientState.ERROR:
            return not self._should_auto_recover_from_error()

        # DELETED状态会触发重新初始化，不会停止上报
        return False

    def force_reset_error_state(self) -> None:
        """强制重置错误状态（用于手动恢复）"""
        if self.state == ClientState.ERROR:
            logger.info("手动重置错误状态")
            self.set_state(ClientState.UNREGISTERED)
        else:
            logger.info("当前不在错误状态，无需重置")

    def get_error_info(self) -> dict:
        """获取错误状态信息"""
        if self.state != ClientState.ERROR:
            return {"in_error": False}

        current_time = int(time.time())
        error_duration = current_time - self.error_start_time if self.error_start_time > 0 else 0

        return {
            "in_error": True,
            "error_start_time": self.error_start_time,
            "error_duration": error_duration,
            "error_retry_count": self.error_retry_count,
            "auto_recovery_in": max(0, 300 - error_duration),  # 距离自动恢复的时间
            "can_manual_reset": True
        }
    
    def handle_device_deleted_response(self) -> None:
        """处理设备被删除的响应（重新设计版本）"""
        logger.info("检测到设备被删除，开始重新初始化流程...")

        # 设置删除状态
        self.set_state(ClientState.DELETED)

        # 停止当前所有数据采集和上报任务（通过状态控制）
        logger.info("停止当前所有数据采集和上报任务")

        # 触发设备重新初始化流程
        self.reinitialize_device()

        logger.info("设备重新初始化完成，进入休眠重注册模式")

    def reinitialize_device(self) -> None:
        """设备重新初始化流程"""
        logger.info("开始设备重新初始化...")

        try:
            # 1. UUID重新生成
            self._regenerate_client_id()

            # 2. 清空所有与旧设备相关的认证信息
            self._clear_auth_info()

            # 3. 配置重置（保留服务器连接配置，重置设备状态）
            self._reset_device_config()

            # 4. 设置重新初始化状态
            self.set_state(ClientState.REINITIALIZED)

            # 5. 记录重新初始化时间
            self._save_reinit_timestamp()

            logger.info("设备重新初始化完成")

        except Exception as e:
            logger.error("设备重新初始化失败: %s", e)
            self.set_state(ClientState.ERROR)

    def _regenerate_client_id(self) -> None:
        """重新生成客户端ID"""
        import uuid
        from pathlib import Path

        client_id_file = Path("client_id.txt")

        # 删除旧的客户端ID
        if client_id_file.exists():
            old_id = client_id_file.read_text().strip()
            logger.info("删除旧的客户端ID: %s", old_id)
            client_id_file.unlink()

        # 生成新的UUID
        new_id = str(uuid.uuid4())
        client_id_file.write_text(new_id)
        logger.info("生成新的客户端ID: %s", new_id)

    def _clear_auth_info(self) -> None:
        """清空认证信息"""
        from .config import RUNTIME_CONFIG

        # 清空运行时配置中的认证信息
        auth_keys = ["auth_token", "server_id", "report_url"]
        for key in auth_keys:
            if key in RUNTIME_CONFIG:
                old_value = RUNTIME_CONFIG.pop(key, None)
                logger.debug("清空认证信息: %s = %s", key, old_value)

        logger.info("认证信息已清空")

    def _reset_device_config(self) -> None:
        """重置设备配置"""
        # 这里可以重置设备特定的配置，但保留监控配置
        # 目前主要是状态重置，具体配置保持不变
        logger.debug("设备配置已重置")

    def _save_reinit_timestamp(self) -> None:
        """保存重新初始化时间戳"""
        import time

        reinit_data = {
            "reinit_timestamp": int(time.time()),
            "reinit_count": self._get_reinit_count() + 1
        }

        try:
            import json
            reinit_file = Path("reinit_info.json")
            with open(reinit_file, 'w') as f:
                json.dump(reinit_data, f)
            logger.info("重新初始化信息已保存: 第%d次重新初始化", reinit_data["reinit_count"])
        except Exception as e:
            logger.error("保存重新初始化信息失败: %s", e)

    def _get_reinit_count(self) -> int:
        """获取重新初始化次数"""
        try:
            import json
            reinit_file = Path("reinit_info.json")
            if reinit_file.exists():
                with open(reinit_file, 'r') as f:
                    data = json.load(f)
                    return data.get("reinit_count", 0)
        except Exception:
            pass
        return 0


def create_delete_marker() -> None:
    """创建删除标记文件的便捷函数"""
    manager = StateManager()
    manager.create_delete_marker()


def check_and_handle_deletion() -> bool:
    """检查并处理删除操作的便捷函数"""
    manager = StateManager()
    if manager.check_delete_marker():
        manager.handle_deletion()
        return True
    return False
