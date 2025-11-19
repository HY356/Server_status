"""CPU 相关指标采集。"""

import logging
import platform
import re
import subprocess
from typing import Any, Dict, Optional

import psutil

logger = logging.getLogger(__name__)


def _get_cpu_usage() -> float:
    """返回 CPU 占用率百分比。"""
    # interval=1 可获得 1 秒平均负载，更平滑
    return psutil.cpu_percent(interval=1)


def _get_cpu_temperature_windows() -> Optional[float]:
    """Windows下获取CPU温度"""
    # 方法1: 尝试使用WMI查询温度传感器
    try:
        cmd = '''
        $temps = @()

        # 尝试查询MSAcpi_ThermalZoneTemperature
        try {
            $thermalZones = Get-WmiObject -Namespace "root/WMI" -Class "MSAcpi_ThermalZoneTemperature" -ErrorAction SilentlyContinue
            foreach ($zone in $thermalZones) {
                $tempK = $zone.CurrentTemperature / 10
                $tempC = $tempK - 273.15
                if ($tempC -gt 0 -and $tempC -lt 150) {
                    $temps += $tempC
                }
            }
        } catch {}

        # 尝试查询Win32_TemperatureProbe
        try {
            $probes = Get-WmiObject -Class "Win32_TemperatureProbe" -ErrorAction SilentlyContinue
            foreach ($probe in $probes) {
                if ($probe.CurrentReading -ne $null) {
                    $tempC = ($probe.CurrentReading - 2732) / 10
                    if ($tempC -gt 0 -and $tempC -lt 150) {
                        $temps += $tempC
                    }
                }
            }
        } catch {}

        if ($temps.Count -gt 0) {
            ($temps | Measure-Object -Maximum).Maximum
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
                temp = float(result.stdout.strip())
                if 0 < temp < 150:  # 合理的温度范围
                    return temp
            except ValueError:
                pass

    except Exception as e:
        logger.debug("WMI温度查询失败: %s", e)

    # 方法2: 尝试使用LibreHardwareMonitor的WMI接口
    try:
        cmd2 = '''
        try {
            $sensors = Get-WmiObject -Namespace "root/LibreHardwareMonitor" -Class "Sensor" -ErrorAction SilentlyContinue | Where-Object {$_.SensorType -eq "Temperature" -and $_.Name -like "*CPU*"}
            if ($sensors) {
                ($sensors | Measure-Object -Property Value -Maximum).Maximum
            }
        } catch {}
        '''

        result2 = subprocess.run(
            ["powershell", "-Command", cmd2],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result2.returncode == 0 and result2.stdout.strip():
            try:
                temp = float(result2.stdout.strip())
                if 0 < temp < 150:
                    logger.debug("通过LibreHardwareMonitor获取CPU温度: %.1f°C", temp)
                    return temp
            except ValueError:
                pass

    except Exception as e:
        logger.debug("LibreHardwareMonitor温度查询失败: %s", e)

    # 方法3: 尝试使用OpenHardwareMonitor的WMI接口
    try:
        cmd3 = '''
        try {
            $sensors = Get-WmiObject -Namespace "root/OpenHardwareMonitor" -Class "Sensor" -ErrorAction SilentlyContinue | Where-Object {$_.SensorType -eq "Temperature" -and $_.Name -like "*CPU*"}
            if ($sensors) {
                ($sensors | Measure-Object -Property Value -Maximum).Maximum
            }
        } catch {}
        '''

        result3 = subprocess.run(
            ["powershell", "-Command", cmd3],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result3.returncode == 0 and result3.stdout.strip():
            try:
                temp = float(result3.stdout.strip())
                if 0 < temp < 150:
                    logger.debug("通过OpenHardwareMonitor获取CPU温度: %.1f°C", temp)
                    return temp
            except ValueError:
                pass

    except Exception as e:
        logger.debug("OpenHardwareMonitor温度查询失败: %s", e)

    logger.debug("所有Windows CPU温度获取方法都失败")
    return None


def _get_cpu_temperature() -> Optional[float]:
    """返回 CPU 当前最高温度 (°C)。若无法获取返回 None。跨平台支持。"""
    system = platform.system().lower()

    if system == "windows":
        # Windows: 使用WMI查询
        return _get_cpu_temperature_windows()

    # Linux/macOS: 使用psutil
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, NotImplementedError):
        return None

    if not temps:
        return None

    highest = None
    for entries in temps.values():
        for entry in entries:
            if entry.current is not None:
                highest = entry.current if highest is None else max(highest, entry.current)
    return highest


def _get_cpu_power_windows() -> Optional[float]:
    """Windows下获取CPU功耗"""
    # 方法1: 尝试使用性能计数器获取处理器性能信息
    try:
        cmd = '''
        try {
            $value = (Get-Counter -Counter "\\Processor Information(_Total)\\% Processor Performance" -SampleInterval 1 -MaxSamples 1 -ErrorAction SilentlyContinue).CounterSamples.CookedValue
            if ($value -ne $null -and $value -gt 0) {
                $value
            }
        } catch {}
        '''

        result = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            try:
                performance = float(result.stdout.strip())
                if 0 < performance < 1000:
                    # 将性能百分比转换为功耗估算
                    # 假设100%性能对应约100W功耗
                    estimated_power = (performance / 100.0) * 100
                    logger.debug("通过处理器性能计数器估算功耗: %.1fW (性能: %.1f%%)", estimated_power, performance)
                    return estimated_power
            except ValueError:
                pass

    except Exception as e:
        logger.debug("性能计数器功耗获取失败: %s", e)

    # 方法2: 尝试使用LibreHardwareMonitor/OpenHardwareMonitor获取功耗
    try:
        cmd2 = '''
        $power = $null

        # 尝试LibreHardwareMonitor
        try {
            $sensors = Get-WmiObject -Namespace "root/LibreHardwareMonitor" -Class "Sensor" -ErrorAction SilentlyContinue | Where-Object {$_.SensorType -eq "Power" -and $_.Name -like "*CPU*"}
            if ($sensors) {
                $power = ($sensors | Measure-Object -Property Value -Maximum).Maximum
            }
        } catch {}

        # 如果没有找到，尝试OpenHardwareMonitor
        if ($power -eq $null) {
            try {
                $sensors = Get-WmiObject -Namespace "root/OpenHardwareMonitor" -Class "Sensor" -ErrorAction SilentlyContinue | Where-Object {$_.SensorType -eq "Power" -and $_.Name -like "*CPU*"}
                if ($sensors) {
                    $power = ($sensors | Measure-Object -Property Value -Maximum).Maximum
                }
            } catch {}
        }

        if ($power -ne $null) {
            $power
        }
        '''

        result2 = subprocess.run(
            ["powershell", "-Command", cmd2],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result2.returncode == 0 and result2.stdout.strip():
            try:
                power = float(result2.stdout.strip())
                if 0 < power < 1000:
                    logger.debug("通过硬件监控软件获取CPU功耗: %.1fW", power)
                    return power
            except ValueError:
                pass

    except Exception as e:
        logger.debug("硬件监控软件功耗获取失败: %s", e)

    # 方法3: 基于CPU使用率的粗略功耗估算
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent >= 0:
            # 基于CPU使用率的粗略功耗估算
            # 现代CPU: 空载约15-25W，满载约65-125W
            base_power = 20  # 基础功耗
            max_additional_power = 80  # 最大额外功耗
            estimated_power = base_power + (cpu_percent / 100.0) * max_additional_power
            logger.debug("使用CPU使用率估算功耗: %.1fW (基于%.1f%%使用率)", estimated_power, cpu_percent)
            return estimated_power
    except Exception as e:
        logger.debug("CPU使用率功耗估算失败: %s", e)

    return None


def _get_cpu_power() -> Optional[float]:
    """尝试获取 CPU 当前功耗 (W)。跨平台支持。"""
    system = platform.system().lower()

    if system == "linux":
        # Linux: 使用 sensors 命令
        try:
            output = subprocess.check_output(["sensors", "-u"], text=True)
            # 示例: power1_input: 34.56
            match = re.search(r"power1_input:\s+([\d.]+)", output)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass
        except (FileNotFoundError, subprocess.CalledProcessError):
            logger.debug("sensors 命令不可用，无法读取 CPU 功耗")

    elif system == "windows":
        # Windows: 使用性能计数器或WMI
        return _get_cpu_power_windows()

    elif system == "darwin":  # macOS
        # macOS: 暂时不支持，返回 None
        logger.debug("macOS 平台暂不支持 CPU 功耗监控")

    return None


def _get_cpu_name_windows() -> Optional[str]:
    """Windows下获取CPU友好名称"""
    try:
        # 方法1: 使用WMI查询Win32_Processor获取CPU名称
        cmd = '''
        $cpu = Get-WmiObject -Class "Win32_Processor" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cpu) {
            $cpu.Name.Trim()
        }
        '''

        result = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            cpu_name = result.stdout.strip()
            if cpu_name and cpu_name != "":
                logger.debug("通过WMI获取CPU名称: %s", cpu_name)
                return cpu_name

        # 方法2: 使用CIM查询（较新的方法）
        cmd2 = '''
        try {
            $cpu = Get-CimInstance -ClassName "Win32_Processor" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($cpu) {
                $cpu.Name.Trim()
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
            cpu_name = result2.stdout.strip()
            if cpu_name and cpu_name != "":
                logger.debug("通过CIM获取CPU名称: %s", cpu_name)
                return cpu_name

        # 方法3: 使用WMIC命令
        try:
            result3 = subprocess.run(
                ["wmic", "cpu", "get", "Name", "/format:value"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result3.returncode == 0:
                for line in result3.stdout.split('\n'):
                    if line.startswith('Name='):
                        cpu_name = line.split('=', 1)[1].strip()
                        if cpu_name and cpu_name != "":
                            logger.debug("通过WMIC获取CPU名称: %s", cpu_name)
                            return cpu_name

        except Exception as e:
            logger.debug("WMIC CPU名称查询失败: %s", e)

    except Exception as e:
        logger.debug("Windows CPU名称获取失败: %s", e)

    return None


def _get_cpu_info() -> Dict[str, Any]:
    """获取CPU基本信息。跨平台支持。"""
    cpu_info = {
        "name": "Unknown",
        "cores": psutil.cpu_count(logical=False),
        "threads": psutil.cpu_count(logical=True),
        "frequency_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None
    }

    system = platform.system().lower()

    if system == "linux":
        # Linux: 从 /proc/cpuinfo 获取CPU型号
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        cpu_info["name"] = line.split(":")[1].strip()
                        break
        except Exception:
            pass

    elif system == "windows":
        # Windows: 使用WMI获取更友好的CPU名称
        cpu_name = _get_cpu_name_windows()
        if cpu_name:
            cpu_info["name"] = cpu_name
        else:
            # 备用方法：使用 platform 模块
            try:
                cpu_info["name"] = platform.processor()
            except Exception:
                pass

    elif system == "darwin":  # macOS
        # macOS: 使用 sysctl 命令
        try:
            output = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True)
            cpu_info["name"] = output.strip()
        except Exception:
            pass

    return cpu_info

def collect() -> Dict[str, Any]:
    """收集 CPU 指标。"""
    metrics = {
        "usage_percent": _get_cpu_usage(),
        "temperature_c": _get_cpu_temperature(),
        "power_w": _get_cpu_power(),
    }
    metrics.update(_get_cpu_info())
    return metrics 