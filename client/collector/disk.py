"""磁盘使用率与硬件信息采集。支持返回每块物理硬盘型号。"""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
from typing import Any, Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)


def _get_disk_model_windows(drive_letter: str) -> Optional[str]:
    """Windows下获取磁盘型号"""
    try:
        import subprocess

        # 简化的方法：直接通过驱动器字母获取对应的物理磁盘
        drive = drive_letter.rstrip(':\\')
        cmd = f'''
        $drive = "{drive}:"
        $disk = Get-WmiObject -Query "ASSOCIATORS OF {{Win32_LogicalDisk.DeviceID='$drive'}} WHERE AssocClass=Win32_LogicalDiskToPartition" |
                ForEach-Object {{
                    Get-WmiObject -Query "ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='$($_.DeviceID)'}} WHERE AssocClass=Win32_DiskDriveToDiskPartition"
                }} | Select-Object -First 1
        if ($disk) {{
            $disk.Model
        }}
        '''

        result = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            model = result.stdout.strip()
            if model and model != "" and model != "null":
                return model

        # 备用方法：如果上面的方法失败，尝试更简单的方法
        # 获取第一个物理磁盘的型号（适用于单磁盘系统）
        cmd2 = '''
        $disks = Get-WmiObject -Class Win32_DiskDrive | Where-Object {$_.MediaType -eq "Fixed hard disk media"}
        if ($disks) {
            $disks[0].Model
        }
        '''

        result2 = subprocess.run(
            ["powershell", "-Command", cmd2],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result2.returncode == 0 and result2.stdout.strip():
            model = result2.stdout.strip()
            if model and model != "" and model != "null":
                logger.debug("使用备用方法获取磁盘型号: %s", model)
                return model

    except Exception as e:
        logger.debug("Windows磁盘型号获取失败: %s", e)

    return None


def _get_disk_model_macos(dev_path: str) -> Optional[str]:
    """macOS下获取磁盘型号"""
    try:
        # 使用diskutil获取磁盘信息
        result = subprocess.run(
            ["diskutil", "info", dev_path],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if "Device / Media Name:" in line:
                    model = line.split(":", 1)[1].strip()
                    if model and model != "":
                        return model

    except Exception as e:
        logger.debug("macOS磁盘型号获取失败: %s", e)

    return None


def _get_disk_model(dev_path: str) -> Optional[str]:
    """获取物理磁盘型号。跨平台支持。

    逻辑：
    - Linux: 使用 lsblk 和 sysfs
    - Windows: 使用 WMI
    - macOS: 使用 diskutil
    """
    system = platform.system().lower()

    if system == "windows":
        # Windows: 从设备路径提取驱动器字母
        if len(dev_path) >= 2 and dev_path[1] == ':':
            drive_letter = dev_path[:2] + '\\'
            return _get_disk_model_windows(drive_letter)
        return None

    elif system == "darwin":  # macOS
        return _get_disk_model_macos(dev_path)

    elif system != "linux":
        # 其他系统暂不支持
        return None
    try:
        output = subprocess.check_output(
            ["lsblk", "-dn", "-o", "MODEL", dev_path],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if output:
            return output
    except FileNotFoundError:
        pass  # lsblk 不存在
    except Exception:
        pass
    except Exception:  # pylint: disable=broad-except
        pass

    base = os.path.basename(dev_path)
    # 处理 NVMe 分区，如 nvme0n1p1 → nvme0n1
    base = re.sub(r"p\d+$", "", base)
    # 处理普通盘分区，如 sda1 → sda
    base = re.sub(r"\d+$", "", base)
    physical_dev = os.path.join("/dev", base)

    try:
        output = subprocess.check_output(
            ["lsblk", "-dn", "-o", "MODEL", physical_dev],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if output:
            return output
    except Exception:
        pass

    # 如果还是空，再查父块设备（PKNAME）
    try:
        parent = subprocess.check_output(
            ["lsblk", "-no", "PKNAME", dev_path], text=True, stderr=subprocess.DEVNULL
        ).strip()
        if parent:
            parent_dev = f"/dev/{parent}"
            out_parent = subprocess.check_output(
                ["lsblk", "-dn", "-o", "MODEL", parent_dev], text=True, stderr=subprocess.DEVNULL
            ).strip()
            if out_parent:
                return out_parent
            # 再查 sysfs
            sys_model_parent = f"/sys/block/{parent}/device/model"
            if os.path.exists(sys_model_parent):
                with open(sys_model_parent, "r") as f:
                    c = f.read().strip()
                    if c:
                        return c
    except Exception:
        pass

    # sysfs fallback
    sys_model_path = f"/sys/block/{base}/device/model"
    try:
        if os.path.exists(sys_model_path):
            with open(sys_model_path, "r") as f:
                content = f.read().strip()
                if content:
                    return content
    except Exception:
        pass

    return None


def _should_monitor_partition(part) -> bool:
    """判断是否应该监控该分区"""
    system = platform.system().lower()

    # 过滤掉空文件系统
    if not part.fstype or part.fstype == "":
        return False

    if system == "windows":
        # Windows: 只监控主要驱动器 (C:\, D:\, 等)
        if len(part.mountpoint) == 3 and part.mountpoint.endswith(":\\"):
            # 排除一些特殊驱动器
            drive_letter = part.mountpoint[0].upper()
            if drive_letter in ['A', 'B']:  # 软盘驱动器
                return False
            return True
        return False

    elif system == "linux":
        # Linux: 排除特殊文件系统
        special_fs = ['tmpfs', 'devtmpfs', 'sysfs', 'proc', 'devpts', 'cgroup', 'pstore', 'squashfs']
        if part.fstype in special_fs:
            return False

        # 排除特殊挂载点
        special_mounts = ['/dev', '/proc', '/sys', '/run', '/boot/efi', '/snap', '/var/snap']
        if any(part.mountpoint.startswith(mount) for mount in special_mounts):
            return False

        # 排除snap包挂载点（更精确的匹配）
        if '/snap/' in part.mountpoint:
            return False

        # 排除loop设备（通常是snap包）
        if part.device.startswith('/dev/loop'):
            return False

        # 只监控主要的物理分区（通常挂载在根目录或有意义的挂载点）
        # 允许的挂载点模式
        allowed_patterns = [
            '/',           # 根分区
            '/home',       # 家目录分区
            '/var',        # var分区
            '/usr',        # usr分区
            '/opt',        # opt分区
            '/tmp',        # tmp分区（如果是独立分区）
            '/boot',       # boot分区（但不是/boot/efi）
        ]

        # 检查是否是允许的挂载点或其子目录
        is_allowed = False
        for pattern in allowed_patterns:
            if part.mountpoint == pattern or part.mountpoint.startswith(pattern + '/'):
                # 但要排除snap相关的子目录
                if '/snap' not in part.mountpoint:
                    is_allowed = True
                    break

        # 如果不在允许列表中，检查是否是用户自定义的挂载点
        # 通常用户挂载点会在/mnt或/media下
        if not is_allowed:
            user_mount_patterns = ['/mnt/', '/media/']
            for pattern in user_mount_patterns:
                if part.mountpoint.startswith(pattern):
                    is_allowed = True
                    break

        return is_allowed

    elif system == "darwin":  # macOS
        # macOS: 排除特殊文件系统
        special_fs = ['devfs', 'autofs', 'mtmfs']
        if part.fstype in special_fs:
            return False

        return True

    return True


def collect() -> List[Dict[str, Any]]:
    """返回所有物理分区的使用情况，并附带硬盘型号。跨平台支持。"""
    disks: List[Dict[str, Any]] = []

    try:
        partitions = psutil.disk_partitions(all=False)
        logger.info("磁盘采集: 发现%d个分区", len(partitions))

        for part in partitions:
            logger.debug("检查分区: %s (%s, %s)", part.mountpoint, part.device, part.fstype)
            # 判断是否应该监控该分区
            should_monitor = _should_monitor_partition(part)
            logger.debug("分区 %s 监控决定: %s", part.mountpoint, should_monitor)
            if not should_monitor:
                continue

            try:
                usage = psutil.disk_usage(part.mountpoint)
                model = _get_disk_model(part.device)

                disk_info = {
                    "device": part.device,
                    "model": model,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                }
                disks.append(disk_info)
                logger.debug("添加磁盘: %s (%.1f%% 使用)", part.mountpoint, usage.percent)

            except (PermissionError, FileNotFoundError, OSError) as e:
                # 某些分区可能无法访问，跳过
                logger.debug("无法访问分区 %s: %s", part.mountpoint, e)
                continue

    except Exception as e:
        logger.error("磁盘采集时发生错误: %s", e)

    logger.info("磁盘采集完成: 共%d个分区", len(disks))
    return disks