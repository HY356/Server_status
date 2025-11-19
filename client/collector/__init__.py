"""采集所有硬件指标。"""

import socket
import time
from typing import Dict, Any

from ..config import get_monitor_config, get_disk_paths
from .cpu import collect as collect_cpu
from .memory import collect as collect_memory
from .disk import collect as collect_disk
from .gpu import collect as collect_gpu
from ..identity import get_client_id


def _has_invalid_disk_paths(paths: list, system: str) -> bool:
    """检查是否包含明显无效的磁盘路径"""
    if not paths:
        return False

    for path in paths:
        # 检查是否为纯数字或明显无效的路径
        if path.isdigit():  # 纯数字路径，如 "1", "2"
            return True

        if system == "windows":
            # Windows下，有效路径应该是 "C:\", "D:\" 等格式
            if not (len(path) >= 2 and path[1] == ':'):
                return True
        elif system in ["linux", "darwin"]:
            # Linux/macOS下，有效路径应该以 "/" 开头
            if not path.startswith('/'):
                return True

    return False


def collect_all() -> Dict[str, Any]:
    """采集所有硬件指标并返回统一的 dict。"""
    timestamp = int(time.time())
    data = {
        "timestamp": timestamp,
        "client_id": get_client_id(),
        "hostname": socket.gethostname(),
    }

    # 记录实际采集的监控项数量
    collected_items = 0

    # CPU 监控
    if get_monitor_config("cpu", "enabled"):
        cpu_data = collect_cpu()
        # 根据配置过滤字段
        if not get_monitor_config("cpu", "collect_temp"):
            cpu_data.pop("temperature_c", None)
        if not get_monitor_config("cpu", "collect_power"):
            cpu_data.pop("power_w", None)
        data["cpu"] = cpu_data
        collected_items += 1

    # 内存监控
    if get_monitor_config("memory", "enabled"):
        data["memory"] = collect_memory()
        collected_items += 1

    # 磁盘监控
    if get_monitor_config("disk", "enabled"):
        paths = get_disk_paths()
        disk_data = collect_disk()

        # 调试信息
        import logging
        import platform
        logger = logging.getLogger(__name__)
        logger.info("磁盘采集: 配置路径=%s, 采集到%d个分区", paths, len(disk_data))

        # 如果配置的路径为空，或者配置了无效路径，则监控所有主要分区
        system = platform.system().lower()
        should_use_all = (
            not paths or
            (system == "windows" and "/" in paths) or  # Windows下配置了Linux路径
            (system in ["linux", "darwin"] and any(p.endswith(":\\") for p in paths)) or  # Linux/Mac下配置了Windows路径
            _has_invalid_disk_paths(paths, system)  # 配置了明显无效的路径
        )

        if should_use_all:
            data["disk"] = disk_data
            # 详细说明使用所有分区的原因
            if not paths:
                reason = "配置路径为空"
            elif system == "windows" and "/" in paths:
                reason = "Windows下配置了Linux路径"
            elif system in ["linux", "darwin"] and any(p.endswith(":\\") for p in paths):
                reason = "Linux/macOS下配置了Windows路径"
            elif _has_invalid_disk_paths(paths, system):
                reason = f"配置了无效路径 {paths}"
            else:
                reason = "其他原因"
            logger.info("使用所有分区: %d个 (原因: %s)", len(disk_data), reason)
        else:
            # 只保留配置的路径
            filtered_disks = [d for d in disk_data if d.get("mountpoint") in paths]
            data["disk"] = filtered_disks
            logger.info("过滤后分区: %d个 (匹配路径: %s)", len(filtered_disks), paths)

        collected_items += 1

    # GPU 监控
    if get_monitor_config("gpu", "enabled"):
        gpu_data = collect_gpu()
        # 根据配置过滤字段
        for gpu in gpu_data:
            if not get_monitor_config("gpu", "collect_temp"):
                gpu.pop("temperature_c", None)
            if not get_monitor_config("gpu", "collect_power"):
                gpu.pop("power_w", None)
        data["gpus"] = gpu_data
        collected_items += 1

    # 记录采集情况
    logger.debug("本次采集了 %d 个监控项", collected_items)

    # 如果没有采集任何监控项，返回 None 表示无需上报
    if collected_items == 0:
        logger.info("所有监控项均已禁用，跳过数据采集")
        return None

    return data
