"""将缓存中的数据发送到服务端。"""

import json
import logging
from typing import List, Dict, Any

import requests

from .cache import Cache
from .config import API_ENDPOINT, SEND_BATCH_SIZE, RUNTIME_CONFIG
from .timing_config import HTTP_TIMEOUT
from .identity import get_client_id, get_auth_token

# 新增: 安全浮点转换，避免 None 导致日志格式化失败
_sf = lambda v: 0.0 if v is None else v  # noqa: E731

logger = logging.getLogger(__name__)


class Sender:
    """负责从本地缓存取出数据并发送到服务端。"""

    def __init__(self, cache: Cache, deletion_callback=None, monitor_config=None):
        self.cache = cache
        self.deletion_callback = deletion_callback  # 删除回调函数
        self.monitor_config = monitor_config  # 监控配置管理器
        # 不再在构造时固定client_id和token，而是每次发送时动态获取

    def send_immediate(self, metrics: Dict[str, Any]) -> bool:
        """立即发送一条指标数据（不经过缓存）。
        
        Args:
            metrics: 要发送的指标数据
            
        Returns:
            bool: 是否发送成功
        """
        report_url = RUNTIME_CONFIG.get("report_url", API_ENDPOINT)
        if not report_url:
            logger.debug("未配置上报地址，跳过发送")
            return False

        # 动态获取最新的认证信息
        current_client_id = get_client_id()
        current_token = get_auth_token()

        # 确保数据中包含最新的 client_id
        metrics["client_id"] = current_client_id

        try:
            headers = {
                "X-Auth-Token": current_token,
                "Content-Type": "application/json"
            }
            logger.info("立即发送指标到 %s", report_url)
            resp = requests.post(
                report_url,
                json=metrics,
                timeout=HTTP_TIMEOUT,
                headers=headers
            )
            
            if 200 <= resp.status_code < 300:
                try:
                    # 解析响应，获取新配置
                    response_data = resp.json()
                    logger.info("服务端原始响应: %s", resp.text)
                    
                    # 检查响应状态
                    status = response_data.get("status")
                    if status == "deleted":
                        logger.warning("数据上报时收到设备删除响应")
                        if self.deletion_callback:
                            self.deletion_callback()
                        return False
                    elif status != "accepted":
                        logger.error("服务端拒绝了此次上报: %s", response_data.get("message", "未知原因"))
                        return False

                    # 检查服务器状态
                    if not response_data.get("is_active", True):
                        logger.error("服务器已禁用监控，停止上报")
                        return False
                    
                    # 更新配置
                    
                    
                    # 更新服务器ID（如果存在）
                    if "server_id" in response_data:
                        RUNTIME_CONFIG["server_id"] = response_data["server_id"]
                        logger.info("服务器ID: %s", response_data["server_id"])
                    
                    # 更新上报间隔
                    if "report_interval" in response_data:
                        old_interval = RUNTIME_CONFIG["report_interval"]
                        new_interval = response_data["report_interval"]
                        if old_interval != new_interval:
                            logger.info("上报间隔已更新: %d -> %d 秒", old_interval, new_interval)
                            RUNTIME_CONFIG["report_interval"] = new_interval
                    
                    # 更新上报URL（如果存在）
                    if "report_url" in response_data:
                        RUNTIME_CONFIG["report_url"] = response_data["report_url"]
                        logger.info("上报URL已更新: %s", response_data["report_url"])
                    
                    # 更新监控项配置
                    if "monitor_items" in response_data:
                        for item, config in response_data["monitor_items"].items():
                            if item not in RUNTIME_CONFIG["monitor_items"]:
                                RUNTIME_CONFIG["monitor_items"][item] = {}

                            for key, value in config.items():
                                old_value = RUNTIME_CONFIG["monitor_items"][item].get(key)
                                RUNTIME_CONFIG["monitor_items"][item][key] = value

                                if old_value != value:
                                    if key == "enabled":
                                        logger.info("监控项 %s 已%s", item, "启用" if value else "禁用")
                                    elif key == "paths":
                                        logger.info("监控项 %s 路径已更新: %s", item, value)
                                    else:
                                        logger.info("监控项 %s 的 %s 已%s",
                                            item, key, "启用" if value else "禁用")

                            # 特殊处理磁盘监控配置兼容性
                            if item == "disk" and "paths" not in config:
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

                    # 更新监控模式配置
                    if "monitor_config" in response_data and self.monitor_config:
                        self.monitor_config.update_config(response_data["monitor_config"])
                        RUNTIME_CONFIG["monitor_config"] = response_data["monitor_config"]
                    
                    logger.info("成功发送实时数据")
                    # 打印发送的数据内容
                    logger.info("上报数据详情:")
                    if "cpu" in metrics:
                        logger.info("  CPU %s (%d核%d线程): 使用率=%.1f%%, 频率=%.1fMHz, 温度=%.1f°C, 功耗=%.1fW",
                            metrics["cpu"].get("name", "Unknown"),
                            metrics["cpu"].get("cores", 0),
                            metrics["cpu"].get("threads", 0),
                            _sf(metrics["cpu"].get("usage_percent")),
                            _sf(metrics["cpu"].get("frequency_mhz")),
                            _sf(metrics["cpu"].get("temperature_c")),
                            _sf(metrics["cpu"].get("power_w")))
                    if "memory" in metrics:
                        logger.info("  内存: 频率=%.1fMHz, 使用率=%.1f%%, 已用=%.1fGB/%.1fGB",
                            _sf(metrics["memory"].get("frequency_mhz")),
                            metrics["memory"].get("percent", 0),
                            metrics["memory"].get("used", 0) / 1024**3,
                            metrics["memory"].get("total", 0) / 1024**3)
                    if "disk" in metrics:
                        for disk in metrics["disk"]:
                            logger.info("  磁盘 %s (%s): 使用率=%.1f%%, 已用=%.1fGB/%.1fGB",
                                disk.get("mountpoint", "unknown"),
                                disk.get("model") or "unknown",
                                disk.get("percent", 0),
                                disk.get("used", 0) / 1024**3,
                                disk.get("total", 0) / 1024**3)
                    if "gpus" in metrics:
                        for gpu in metrics["gpus"]:
                            logger.info("  GPU %s: 使用率=%.1f%%, 显存=%.1f%%, 功耗=%.1fW",
                                gpu.get("name", "unknown"),
                                _sf(gpu.get("util_percent")),
                                _sf(gpu.get("memory_util_percent")),
                                _sf(gpu.get("power_w")))
                    return True
                except ValueError as e:
                    logger.warning("解析服务端响应失败: %s", e)
                    return True  # 数据发送成功，仅配置解析失败
                except KeyError as e:
                    logger.warning("处理服务端配置时出错: %s", e)
                    return True  # 数据发送成功，仅配置更新失败
            elif resp.status_code == 403:
                # 检查是否是设备删除错误
                try:
                    error_data = resp.json()
                    if error_data.get("error_code") == "DEVICE_DELETED":
                        logger.warning("数据上报时收到设备删除错误码")
                        if self.deletion_callback:
                            self.deletion_callback()
                        return False
                except (json.JSONDecodeError, ValueError):
                    pass

                # 尝试解析JSON并正确显示中文
                try:
                    error_data = resp.json()
                    logger.error("实时发送失败(%s): %s", resp.status_code, json.dumps(error_data, ensure_ascii=False, indent=2))
                except (json.JSONDecodeError, ValueError):
                    logger.error("实时发送失败(%s): %s", resp.status_code, resp.text)
                logger.error("请求数据: %s", metrics)
                return False
            else:
                # 尝试解析JSON并正确显示中文
                try:
                    error_data = resp.json()
                    logger.error("实时发送失败(%s): %s", resp.status_code, json.dumps(error_data, ensure_ascii=False, indent=2))
                except (json.JSONDecodeError, ValueError):
                    logger.error("实时发送失败(%s): %s", resp.status_code, resp.text)
                logger.error("请求数据: %s", metrics)
                return False
                
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("实时发送异常: %s", exc)
            return False

    def send(self) -> None:
        """尝试发送未上报的数据。

        发送成功后在本地缓存中标记 sent=1；发送失败则保留稍后重试。"""
        # 如果未配置上报地址，跳过发送
        if not API_ENDPOINT:
            logger.debug("未配置上报地址，跳过发送")
            return

        batch = self.cache.get_unsent(SEND_BATCH_SIZE)
        if not batch:
            return

        # 动态获取最新的认证信息
        current_client_id = get_client_id()
        current_token = get_auth_token()

        # 对缓存数据做一次补丁，保证 GPU 数值字段不是 None，并更新client_id
        payload: List[dict] = []
        for item in batch:
            data = item["data"]
            # 更新为最新的client_id（防止使用缓存中的旧client_id）
            data["client_id"] = current_client_id

            for gpu in data.get("gpus", []):
                for key in ("memory_total", "memory_used", "memory_util_percent", "util_percent", "frequency_mhz"):
                    if gpu.get(key) is None:
                        gpu[key] = 0
            payload.append(data)
        ids = [item["id"] for item in batch]

        report_url = RUNTIME_CONFIG.get("report_url", API_ENDPOINT)

        # 准备HTTP请求
        headers = {
            "X-Auth-Token": current_token,
            "Content-Type": "application/json"
        }
        
        logger.info("发送 %d 条缓存指标到 %s", len(payload), report_url)

        try:
            resp = requests.post(report_url, json=payload, timeout=HTTP_TIMEOUT, headers=headers)
            if 200 <= resp.status_code < 300:
                try:
                    # 解析响应，获取新配置
                    response_data = resp.json()
                    logger.info("服务端原始响应: %s", resp.text)
                    
                    # 检查响应状态
                    status = response_data.get("status")
                    if status == "deleted":
                        logger.warning("批量上报时收到设备删除响应")
                        if self.deletion_callback:
                            self.deletion_callback()
                        return
                    elif status != "accepted":
                        logger.error("服务端拒绝了此次上报: %s", response_data.get("message", "未知原因"))
                        return

                    # 检查服务器状态
                    if not response_data.get("is_active", True):
                        logger.error("服务器已禁用监控，停止上报")
                        return False
                    
                    # 更新配置
                    
                    
                    # 更新服务器ID（如果存在）
                    if "server_id" in response_data:
                        RUNTIME_CONFIG["server_id"] = response_data["server_id"]
                        logger.info("服务器ID: %s", response_data["server_id"])
                    
                    # 更新上报间隔
                    if "report_interval" in response_data:
                        old_interval = RUNTIME_CONFIG["report_interval"]
                        new_interval = response_data["report_interval"]
                        if old_interval != new_interval:
                            logger.info("上报间隔已更新: %d -> %d 秒", old_interval, new_interval)
                            RUNTIME_CONFIG["report_interval"] = new_interval
                    
                    # 更新上报URL（如果存在）
                    if "report_url" in response_data:
                        RUNTIME_CONFIG["report_url"] = response_data["report_url"]
                        logger.info("上报URL已更新: %s", response_data["report_url"])
                    
                    # 更新监控项配置
                    if "monitor_items" in response_data:
                        for item, config in response_data["monitor_items"].items():
                            if item not in RUNTIME_CONFIG["monitor_items"]:
                                RUNTIME_CONFIG["monitor_items"][item] = {}

                            for key, value in config.items():
                                old_value = RUNTIME_CONFIG["monitor_items"][item].get(key)
                                RUNTIME_CONFIG["monitor_items"][item][key] = value

                                if old_value != value:
                                    if key == "enabled":
                                        logger.info("监控项 %s 已%s", item, "启用" if value else "禁用")
                                    elif key == "paths":
                                        logger.info("监控项 %s 路径已更新: %s", item, value)
                                    else:
                                        logger.info("监控项 %s 的 %s 已%s",
                                            item, key, "启用" if value else "禁用")

                            # 特殊处理磁盘监控配置兼容性
                            if item == "disk" and "paths" not in config:
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

                    # 更新监控模式配置
                    if "monitor_config" in response_data and self.monitor_config:
                        self.monitor_config.update_config(response_data["monitor_config"])
                        RUNTIME_CONFIG["monitor_config"] = response_data["monitor_config"]
                    
                    # 标记数据已发送
                    self.cache.mark_sent(ids)
                    logger.info("成功发送 %d 条采集数据", len(ids))
                    
                    # 打印发送的数据内容
                    for idx, data in enumerate(payload, 1):
                        logger.info("数据 %d/%d:", idx, len(payload))
                        if "cpu" in data:
                            logger.info("  CPU: 使用率=%.1f%%, 温度=%.1f°C, 功耗=%.1fW",
                                _sf(data["cpu"].get("usage_percent")),
                                _sf(data["cpu"].get("temperature_c")),
                                _sf(data["cpu"].get("power_w")))
                        if "memory" in data:
                            logger.info("  内存: 使用率=%.1f%%, 已用=%.1fGB/%.1fGB",
                                data["memory"].get("percent", 0),
                                data["memory"].get("used", 0) / 1024**3,
                                data["memory"].get("total", 0) / 1024**3)
                        if "disk" in data:
                            for disk in data["disk"]:
                                logger.info("  磁盘 %s (%s): 使用率=%.1f%%, 已用=%.1fGB/%.1fGB",
                                    disk.get("mountpoint", "unknown"),
                                    disk.get("model") or "unknown",
                                    disk.get("percent", 0),
                                    disk.get("used", 0) / 1024**3,
                                    disk.get("total", 0) / 1024**3)
                        if "gpus" in data:
                            for gpu in data["gpus"]:
                                logger.info("  GPU %s: 频率=%.1fMHz, 使用率=%.1f%%, 显存=%.1f%%, 功耗=%.1fW",
                                    gpu.get("name", "unknown"),
                                    _sf(gpu.get("frequency_mhz")),
                                    _sf(gpu.get("util_percent")),
                                    _sf(gpu.get("memory_util_percent")),
                                    _sf(gpu.get("power_w")))
                except ValueError as e:
                    logger.warning("解析服务端响应失败: %s", e)
                except KeyError as e:
                    logger.warning("处理服务端配置时出错: %s", e)
            elif resp.status_code == 403:
                # 检查是否是设备删除错误
                try:
                    error_data = resp.json()
                    if error_data.get("error_code") == "DEVICE_DELETED":
                        logger.warning("批量上报时收到设备删除错误码")
                        if self.deletion_callback:
                            self.deletion_callback()
                        return
                except (json.JSONDecodeError, ValueError):
                    pass

                # 尝试解析JSON并正确显示中文
                try:
                    error_data = resp.json()
                    logger.error("上报失败(%s): %s", resp.status_code, json.dumps(error_data, ensure_ascii=False, indent=2))
                except (json.JSONDecodeError, ValueError):
                    logger.error("上报失败(%s): %s", resp.status_code, resp.text)
                logger.error("请求数据: %s", payload)
            else:
                # 尝试解析JSON并正确显示中文
                try:
                    error_data = resp.json()
                    logger.error("上报失败(%s): %s", resp.status_code, json.dumps(error_data, ensure_ascii=False, indent=2))
                except (json.JSONDecodeError, ValueError):
                    logger.error("上报失败(%s): %s", resp.status_code, resp.text)
                logger.error("请求数据: %s", payload)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("上报时发生异常: %s", exc) 