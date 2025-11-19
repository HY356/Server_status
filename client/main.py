"""客户端入口脚本。"""

import logging
import socket
import sys
import time
from typing import Optional, Dict, Any

import requests
from requests.exceptions import RequestException

from .cache import Cache
from .collector import collect_all
from .config import (
    API_ENDPOINT,
    AUTH_TOKEN,
    DB_PATH,
    REGISTER_URL,
    RUNTIME_CONFIG,
    get_report_interval,
    get_monitor_mode_config,
    is_monitoring_enabled,
    is_server_active,
)
from .timing_config import (
    HTTP_TIMEOUT, REGISTER_TIMEOUT, REGISTER_REJECTED_RETRY_INTERVAL,
    ERROR_STATE_RETRY_INTERVAL, REGISTER_FAILED_RETRY_INTERVAL,
    SERVER_INACTIVE_RETRY_INTERVAL, CONFIG_INCOMPLETE_RETRY_INTERVAL,
    get_sleep_retry_interval, CACHE_CLEANUP_INTERVAL
)
from .identity import get_client_id, get_auth_token, get_os_info
from .logger import setup_logging
from .sender import Sender
from .state_manager import StateManager, ClientState
from .monitor_config import MonitorConfig
from .heartbeat import HeartbeatManager


def register_client(max_retries: int = 0, retry_interval: int = 30, state_manager: Optional[StateManager] = None) -> Optional[Dict[str, Any]]:
    """向服务端注册并获取配置。"""
    logger = logging.getLogger(__name__)
    client_id = get_client_id()
    hostname = socket.gethostname()
    os_info = get_os_info()
    my_token = get_auth_token()  # 使用UUID生成我们的token

    payload = {
        "client_id": client_id,
        "hostname": hostname,
        "os": os_info,  # 新增操作系统信息
    }

    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.post(REGISTER_URL, json=payload, timeout=REGISTER_TIMEOUT)

            if resp.status_code == 200:
                logger.info("注册原始响应: %s", resp.text)
                try:
                    config = resp.json()
                    logger.debug("收到注册响应: %s", config)

                    if not isinstance(config, dict):
                        logger.error("注册响应格式错误，期望 dict 但收到 %s", type(config))
                        return None

                    status = config.get("status")
                    if status == "pending":
                        logger.info("注册请求正在等待审核...")
                    elif status == "rejected":
                        reason = config.get("message", "未知原因")
                        logger.error("注册请求被拒绝: %s", reason)
                        logger.info("将在 30 分钟后重试...")
                        return {"status": "rejected", "message": reason}
                    elif status == "deleted":
                        logger.warning("收到设备删除响应，触发重新初始化")
                        if state_manager:
                            state_manager.handle_device_deleted_response()
                        return {"status": "deleted", "action": "reinitialize"}
                    elif status == "accepted":
                        # 验证服务端返回的token
                        server_token = config.get("auth_token")
                        if not server_token:
                            logger.error("服务端未返回认证token")
                            return None
                        
                        if server_token != my_token:
                            logger.error("服务端返回的token验证失败")
                            logger.error("请检查客户端和服务端的 SERVER_SECRET_KEY 是否一致")
                            return None
                        
                        logger.info("Token验证成功")

                        # 检查必需的配置项
                        required_fields = [
                            "server_id", "auth_token", "report_url", 
                            "report_interval", "monitor_items", "is_active"
                        ]
                        missing_fields = [f for f in required_fields if f not in config]
                        if missing_fields:
                            logger.error("注册响应缺少必需字段: %s", missing_fields)
                            logger.error("完整响应: %s", config)
                            return None

                        # 检查monitor_items结构
                        monitor_items = config.get("monitor_items", {})
                        required_monitors = ["cpu", "memory", "disk", "gpu"]
                        missing_monitors = [m for m in required_monitors if m not in monitor_items]
                        if missing_monitors:
                            logger.error("monitor_items缺少必需项: %s", missing_monitors)
                            logger.error("完整响应: %s", config)
                            return None
                        
                        # 使用服务端配置，如果某项未提供则使用默认值
                        full_config = {
                            "status": "accepted",
                            "server_id": config["server_id"],
                            "report_url": config["report_url"],
                            "report_interval": config["report_interval"],
                            "monitor_items": config["monitor_items"],
                            "is_active": config["is_active"],
                            "auth_token": server_token,
                            "message": config.get("message", "注册成功")
                        }

                        logger.info("注册成功: %s", full_config["message"])
                        logger.info(
                            "服务器配置: ID=%s, 上报间隔=%d秒",
                            full_config["server_id"],
                            full_config["report_interval"],
                        )
                        return full_config
                    else:
                        logger.error("未知的注册状态: %s", status)
                        return None

                except ValueError as e:
                    logger.error("解析注册响应JSON失败: %s", e)
                    logger.error("原始响应: %s", resp.text[:200])
                    return None

            elif resp.status_code == 403:
                # 检查是否是设备删除错误
                try:
                    error_data = resp.json()
                    if error_data.get("error_code") == "DEVICE_DELETED":
                        logger.warning("收到设备删除错误码，触发重新初始化")
                        if state_manager:
                            state_manager.handle_device_deleted_response()
                        return {"status": "deleted", "action": "reinitialize"}
                except (json.JSONDecodeError, ValueError):
                    pass

                logger.error("注册失败，状态码: %d", resp.status_code)
                logger.error("响应内容: %s", resp.text)
                return None
            else:
                logger.error("注册失败，状态码: %d", resp.status_code)
                logger.error("响应内容: %s", resp.text)
                return None

        except RequestException as e:
            logger.error("注册请求异常: %s", e)

        if max_retries > 0 and attempt >= max_retries:
            logger.error("达到最大重试次数 %d，退出注册", max_retries)
            return None

        logger.info(
            "等待 %d 秒后进行第 %d 次重试... (按 Ctrl+C 退出)",
            retry_interval,
            attempt + 1,
        )
        try:
            time.sleep(retry_interval)
        except KeyboardInterrupt:
            logger.info("用户中断，退出注册")
            return None


def update_config(config: Dict[str, Any], monitor_config: Optional[MonitorConfig] = None) -> None:
    """更新全局配置。"""
    from . import config as config_module
    logger = logging.getLogger(__name__)

    # 更新 API 配置
    new_report_url = config.get("report_url")
    if new_report_url:
        config_module.API_ENDPOINT = new_report_url
        RUNTIME_CONFIG["report_url"] = new_report_url
    else:
        # 如果服务端没有提供report_url，保持当前配置
        if "report_url" not in RUNTIME_CONFIG:
            RUNTIME_CONFIG["report_url"] = config_module.API_ENDPOINT

    # 验证服务端返回的token是否与客户端生成的token一致
    server_token = config.get("auth_token")
    client_token = get_auth_token()

    if server_token and server_token == client_token:
        config_module.AUTH_TOKEN = server_token  # 使用验证通过的token
        logger.debug("服务端token验证通过")
    else:
        logger.error("服务端token验证失败: server=%s, client=%s",
                    server_token[:10] + "..." if server_token else "None",
                    client_token[:10] + "..." if client_token else "None")
        config_module.AUTH_TOKEN = client_token  # 使用客户端生成的token
    
    # 更新监控配置
    if "monitor_items" in config:
        # 深度合并监控项配置，保持向后兼容
        for item, item_config in config["monitor_items"].items():
            if item not in RUNTIME_CONFIG["monitor_items"]:
                RUNTIME_CONFIG["monitor_items"][item] = {}

            # 更新配置项
            RUNTIME_CONFIG["monitor_items"][item].update(item_config)

            # 特殊处理磁盘监控配置兼容性
            if item == "disk" and "paths" not in item_config:
                # 新版本服务端不返回paths字段，保持客户端默认配置
                if "paths" not in RUNTIME_CONFIG["monitor_items"][item]:
                    import platform
                    system = platform.system().lower()
                    if system == "windows":
                        RUNTIME_CONFIG["monitor_items"][item]["paths"] = ["C:\\"]
                    else:
                        RUNTIME_CONFIG["monitor_items"][item]["paths"] = ["/"]
                    logger.info("磁盘监控配置兼容性处理: 使用默认路径 %s",
                               RUNTIME_CONFIG["monitor_items"][item]["paths"])

    # 更新上报间隔
    if "report_interval" in config:
        RUNTIME_CONFIG["report_interval"] = config["report_interval"]

    # 更新监控模式配置
    if "monitor_config" in config:
        RUNTIME_CONFIG["monitor_config"] = config["monitor_config"]
        logger.info("监控模式配置已更新: %s", config["monitor_config"])
        # 如果传入了monitor_config实例，也更新它
        if monitor_config:
            monitor_config.update_config(config["monitor_config"])

    logger.info("配置已更新:")
    logger.info("  上报间隔: %d 秒", get_report_interval())
    logger.info("  监控项:")
    for item, settings in RUNTIME_CONFIG["monitor_items"].items():
        logger.info("    %s: %s", item, settings)


def main() -> None:
    # 初始化日志系统
    setup_logging()
    logger = logging.getLogger(__name__)

    # 移除旧的删除检测逻辑，使用新的状态管理

    # 初始化状态管理器
    state_manager = StateManager()

    # 初始化认证token
    from . import config as config_module
    config_module.AUTH_TOKEN = get_auth_token()
    logger.debug("认证Token已初始化: %s", config_module.AUTH_TOKEN[:10] + "..." if config_module.AUTH_TOKEN else "None")

    # 记录启动信息
    logger.info("Server Status Client 启动")
    logger.info("客户端 ID: %s", get_client_id())
    logger.info("操作系统: %s", get_os_info())
    logger.info("主机名: %s", socket.gethostname())
    logger.info("当前状态: %s", state_manager.get_state().value)

    REJECT_RETRY_INTERVAL = 1800  # 30分钟 = 1800秒

    # 初始化缓存和发送器
    cache = Cache(DB_PATH)

    # 初始化监控配置管理器
    monitor_config = MonitorConfig(get_monitor_mode_config())

    # 定义删除回调函数
    def on_device_deleted():
        logger.warning("收到设备删除通知，触发重新初始化")
        state_manager.handle_device_deleted_response()

    sender = Sender(cache, deletion_callback=on_device_deleted, monitor_config=monitor_config)

    # 初始化心跳管理器
    heartbeat_manager = HeartbeatManager(sender, monitor_config)

    # 记录上次活动时间（用于强制心跳检测）
    last_activity_time = int(time.time())

    while True:
        # 检查是否需要停止注册（错误状态检测）
        if state_manager.should_stop_registration():
            current_state = state_manager.get_state()
            if current_state == ClientState.ERROR:
                error_info = state_manager.get_error_info()
                logger.info("检测到错误状态，已持续 %d 秒，重试次数: %d",
                           error_info['error_duration'], error_info['error_retry_count'])
                logger.info("将在 %d 秒后自动恢复，或使用 reset_client_state.py 手动重置",
                           error_info['auto_recovery_in'])

            logger.info("等待%d秒后重试", ERROR_STATE_RETRY_INTERVAL)
            time.sleep(ERROR_STATE_RETRY_INTERVAL)
            continue

        # 设置注册状态
        state_manager.set_state(ClientState.REGISTERING)

        # 检查是否需要进入休眠重注册模式
        if state_manager.should_enter_sleep_retry_mode():
            state_manager.enter_sleep_retry_mode()

            retry_count = 0
            while state_manager.get_state() == ClientState.SLEEP_RETRY:
                # 智能休眠并重试注册
                if not state_manager.sleep_and_retry_register(retry_count):
                    logger.info("用户中断休眠，退出程序")
                    return  # 用户中断时退出main函数

                # 使用新UUID进行注册
                config = register_client(max_retries=0, retry_interval=30, state_manager=state_manager)
                if not config:
                    logger.error("休眠重注册失败，继续休眠")
                    retry_count += 1
                    continue

                # 处理注册响应
                if isinstance(config, dict):
                    action = state_manager.handle_register_response(config)

                    if action == "resume_normal":
                        # 成功注册，立即退出休眠模式
                        logger.info("注册成功，立即恢复正常运行")
                        break
                    elif action == "continue_sleep":
                        # 继续休眠重试
                        retry_count += 1
                        continue
                    elif action == "reinitialize":
                        # 重新初始化，重新开始整个流程
                        retry_count = 0  # 重置重试计数
                        break

        # 正常注册流程
        if state_manager.get_state() != ClientState.REGISTERED:
            config = register_client(max_retries=0, retry_interval=30, state_manager=state_manager)
            if not config:
                logger.error("注册失败，等待%d秒后重试", REGISTER_FAILED_RETRY_INTERVAL)
                state_manager.set_state(ClientState.ERROR)
                time.sleep(REGISTER_FAILED_RETRY_INTERVAL)
                continue

            # 检查注册状态
            if isinstance(config, dict):
                status = config.get("status")
                if status == "pending":
                    continue
                elif status == "rejected":
                    try:
                        logger.info("等待 %d 分钟后重试注册...", REGISTER_REJECTED_RETRY_INTERVAL // 60)
                        time.sleep(REGISTER_REJECTED_RETRY_INTERVAL)
                        continue
                    except KeyboardInterrupt:
                        logger.info("用户中断，退出程序")
                        return  # 用户中断时退出main函数
                elif status == "deleted":
                    # 删除状态已在register_client中处理，重新开始循环
                    continue
                elif status == "accepted":
                    # 设置已注册状态
                    state_manager.set_state(ClientState.REGISTERED)

                    # 更新配置
                    update_config(config, monitor_config)
                    if not config["is_active"]:
                        logger.error("服务器未启用监控，等待%d秒后重试", SERVER_INACTIVE_RETRY_INTERVAL)
                        state_manager.set_state(ClientState.ERROR)
                        time.sleep(SERVER_INACTIVE_RETRY_INTERVAL)
                        continue

                    # 检查配置完整性
                    from . import config as config_module
                    if not all([config_module.API_ENDPOINT, config_module.AUTH_TOKEN]):
                        logger.error("配置不完整，等待%d秒后重试注册", CONFIG_INCOMPLETE_RETRY_INTERVAL)
                        logger.error("API_ENDPOINT: %s", config_module.API_ENDPOINT)
                        logger.error("AUTH_TOKEN: %s", config_module.AUTH_TOKEN[:10] + "..." if config_module.AUTH_TOKEN else "None")
                        state_manager.set_state(ClientState.ERROR)
                        time.sleep(CONFIG_INCOMPLETE_RETRY_INTERVAL)
                        continue

                    # 注册成功后立即采集并发送一次数据
                    try:
                        logger.info("注册成功，立即采集并发送首次数据...")
                        metrics = collect_all()

                        if metrics is None:
                            logger.info("所有监控项均已禁用，跳过首次数据发送")
                        else:
                            logger.info("首次数据采集完成，准备发送")

                            # 使用 send_immediate 直接发送，不经过缓存
                            if sender.send_immediate(metrics):
                                logger.info("首次数据发送成功")
                                # 更新活动时间
                                last_activity_time = int(time.time())
                                # 等待一个完整的间隔时间再开始定时采集
                                logger.info("将在 %d 秒后开始定时采集任务", get_report_interval())
                            else:
                                logger.warning("首次数据发送失败，将通过缓存重试")
                                cache.save(metrics)
                    except Exception as e:
                        logger.error("首次数据发送异常: %s", e)
                        logger.exception(e)  # 打印完整的异常堆栈
                        # 如果采集失败，创建空的metrics避免UnboundLocalError
                        try:
                            if 'metrics' in locals() and metrics is not None:
                                cache.save(metrics)  # 保存到缓存以便后续重试
                        except Exception:
                            logger.error("数据采集失败，无法保存到缓存")

                    # 注册成功，开始采集循环
                    logger.info("开始定时采集，间隔 %d 秒", get_report_interval())

                    # 采集循环（内层循环）
                    while True:
                        try:
                            # 检查是否需要停止（删除检测）
                            if state_manager.should_stop_reporting():
                                logger.info("检测到停止信号，退出采集循环")
                                break

                            # 检查是否需要处理删除状态
                            current_state = state_manager.get_state()
                            if current_state in [ClientState.DELETED, ClientState.REINITIALIZED, ClientState.SLEEP_RETRY]:
                                logger.info("检测到删除相关状态 (%s)，退出采集循环，重新开始注册流程", current_state.value)
                                break  # 退出采集循环，重新开始注册

                            # 检查是否需要强制发送心跳包（防止长时间静默）
                            from .heartbeat import should_force_heartbeat
                            if should_force_heartbeat(last_activity_time):
                                logger.info("长时间静默，发送强制心跳包")
                                if heartbeat_manager.send_heartbeat("长时间静默，强制心跳"):
                                    last_activity_time = int(time.time())

                            # 检查是否需要发送心跳包而不是监控数据
                            should_send_heartbeat, heartbeat_reason = heartbeat_manager.should_send_heartbeat()

                            if should_send_heartbeat:
                                logger.info("%s，发送心跳包", heartbeat_reason)

                                # 发送心跳包
                                if heartbeat_manager.send_heartbeat(heartbeat_reason):
                                    last_activity_time = int(time.time())

                                # 等待下一次检查
                                time.sleep(get_report_interval())
                                continue

                            # 如果到这里，说明应该进行正常的监控数据采集
                            # 采集数据
                            logger.info("开始采集数据...")
                            metrics = collect_all()

                            # 检查是否有数据需要上报
                            if metrics is None:
                                logger.info("无监控数据需要上报，跳过本次采集")
                                # 等待下一次采集
                                time.sleep(get_report_interval())
                                continue

                            logger.debug("采集完成，准备发送")

                            # 保存到缓存
                            cache.save(metrics)

                            # 发送数据
                            sender.send()

                            # 更新活动时间（表示成功与服务端通信）
                            last_activity_time = int(time.time())

                            # 发送后立即检查状态变化（删除回调可能已触发）
                            current_state = state_manager.get_state()
                            if current_state in [ClientState.DELETED, ClientState.REINITIALIZED, ClientState.SLEEP_RETRY]:
                                logger.info("发送后检测到删除相关状态 (%s)，立即退出采集循环", current_state.value)
                                break  # 立即退出采集循环，不等待下一次循环

                            # 清理过期数据
                            cache.prune(CACHE_CLEANUP_INTERVAL)

                            # 等待下一次采集
                            logger.debug("等待 %d 秒后进行下一次采集", get_report_interval())

                        except Exception as e:  # pylint: disable=broad-except
                            logger.exception("主循环异常: %s", e)

                        time.sleep(get_report_interval())

                    # 采集循环结束，回到外层注册循环
                    logger.info("退出采集循环，回到外层注册循环")
                    # 不使用break，让程序自然回到外层while True循环


if __name__ == "__main__":
    main() 