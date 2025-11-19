"""内存相关指标采集。"""

import logging
import platform
import re
import subprocess
from typing import Any, Dict, Optional

import psutil

logger = logging.getLogger(__name__)


def _get_memory_usage() -> Dict[str, Any]:
    """返回内存使用情况。单位 Byte。"""
    mem = psutil.virtual_memory()
    return {
        "total": mem.total,
        "used": mem.used,
        "percent": mem.percent,
        "available": mem.available,
    }


def _get_memory_frequency_windows() -> Optional[int]:
    """Windows下获取内存频率"""
    try:
        # 方法1: 使用WMI查询Win32_PhysicalMemory获取内存频率
        cmd = '''
        $memories = Get-WmiObject -Class "Win32_PhysicalMemory" -ErrorAction SilentlyContinue
        if ($memories) {
            $frequencies = @()
            foreach ($memory in $memories) {
                if ($memory.Speed -ne $null -and $memory.Speed -gt 0) {
                    $frequencies += $memory.Speed
                }
                # 有些系统使用ConfiguredClockSpeed
                if ($memory.ConfiguredClockSpeed -ne $null -and $memory.ConfiguredClockSpeed -gt 0) {
                    $frequencies += $memory.ConfiguredClockSpeed
                }
            }

            if ($frequencies.Count -gt 0) {
                # 返回最高频率
                ($frequencies | Measure-Object -Maximum).Maximum
            }
        }
        '''

        result = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            try:
                freq = int(float(result.stdout.strip()))
                if 100 < freq < 10000:  # 合理的内存频率范围 (100MHz - 10GHz)
                    logger.debug("通过WMI获取内存频率: %dMHz", freq)
                    return freq
            except (ValueError, TypeError):
                pass

        # 方法2: 使用CIM查询（较新的方法）
        cmd2 = '''
        try {
            $memories = Get-CimInstance -ClassName "Win32_PhysicalMemory" -ErrorAction SilentlyContinue
            if ($memories) {
                $frequencies = @()
                foreach ($memory in $memories) {
                    if ($memory.Speed -ne $null -and $memory.Speed -gt 0) {
                        $frequencies += $memory.Speed
                    }
                    if ($memory.ConfiguredClockSpeed -ne $null -and $memory.ConfiguredClockSpeed -gt 0) {
                        $frequencies += $memory.ConfiguredClockSpeed
                    }
                }

                if ($frequencies.Count -gt 0) {
                    ($frequencies | Measure-Object -Maximum).Maximum
                }
            }
        } catch {}
        '''

        result2 = subprocess.run(
            ["powershell", "-Command", cmd2],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result2.returncode == 0 and result2.stdout.strip():
            try:
                freq = int(float(result2.stdout.strip()))
                if 100 < freq < 10000:
                    logger.debug("通过CIM获取内存频率: %dMHz", freq)
                    return freq
            except (ValueError, TypeError):
                pass

        # 方法3: 尝试通过WMIC命令
        try:
            result3 = subprocess.run(
                ["wmic", "memorychip", "get", "Speed", "/format:value"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result3.returncode == 0:
                frequencies = []
                for line in result3.stdout.split('\n'):
                    if line.startswith('Speed='):
                        try:
                            speed = int(line.split('=')[1].strip())
                            if 100 < speed < 10000:
                                frequencies.append(speed)
                        except (ValueError, IndexError):
                            continue

                if frequencies:
                    max_freq = max(frequencies)
                    logger.debug("通过WMIC获取内存频率: %dMHz", max_freq)
                    return max_freq

        except Exception as e:
            logger.debug("WMIC内存频率查询失败: %s", e)

    except Exception as e:
        logger.debug("Windows内存频率获取失败: %s", e)

    return None


def _get_memory_frequency() -> Optional[int]:
    """尝试获取最大内存频率 (MHz)。跨平台支持。"""
    system = platform.system().lower()

    if system == "linux":
        # Linux: 使用 lshw 命令
        try:
            output = subprocess.check_output(["lshw", "-C", "memory"], text=True, stderr=subprocess.DEVNULL)
            matches = re.findall(r"(\d+)MHz", output)
            if matches:
                freqs = [int(m) for m in matches]
                return max(freqs)
        except (FileNotFoundError, subprocess.CalledProcessError):
            logger.debug("lshw 命令不可用，无法读取内存频率")

    elif system == "windows":
        # Windows: 使用WMI查询内存频率
        return _get_memory_frequency_windows()

    elif system == "darwin":  # macOS
        # macOS: 暂时不支持，返回 None
        logger.debug("macOS 平台暂不支持内存频率监控")

    return None


def collect() -> Dict[str, Any]:
    """收集内存指标。"""
    data = _get_memory_usage()
    data["frequency_mhz"] = _get_memory_frequency()
    return data 