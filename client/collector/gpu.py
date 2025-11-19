"""采集 GPU 相关指标。支持 NVIDIA 和 AMD 显卡。"""

import logging
import os
import glob
import platform
import re
import subprocess
from typing import List, Dict, Any, Optional
import json
import shutil

import pynvml

from ..config import get_monitor_config

logger = logging.getLogger(__name__)

NVML_INITIALIZED = False

try:
    pynvml.nvmlInit()
    NVML_INITIALIZED = True
except Exception as e:  # pylint: disable=broad-except
    logger.warning("NVML 初始化失败，NVIDIA GPU 监控不可用: %s", e)


def _collect_nvidia() -> List[Dict[str, Any]]:
    """采集 NVIDIA GPU 指标。"""
    result = []
    try:
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            
            # 获取设备名称
            try:
                raw_name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(raw_name, bytes):
                    name = raw_name.decode()
                else:
                    name = raw_name
            except Exception:  # pylint: disable=broad-except
                name = f"NVIDIA-GPU-{i}"
            
            # 获取利用率
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                util_percent = util.gpu
            except Exception:  # pylint: disable=broad-except
                util_percent = 0
            
            # 获取内存信息
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                memory_total = mem.total
                memory_used = mem.used
                memory_util_percent = memory_used / memory_total * 100
            except Exception:  # pylint: disable=broad-except
                memory_total = 0
                memory_used = 0
                memory_util_percent = 0
            
            # 获取温度
            try:
                temperature = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
            except Exception:  # pylint: disable=broad-except
                temperature = None
            
            # 获取功耗
            try:
                power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            except Exception:  # pylint: disable=broad-except
                power = None
                
            # 获取频率
            try:
                freq = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS)
            except Exception:  # pylint: disable=broad-except
                freq = None
            
            gpu_data = {
                "vendor": "nvidia",
                "index": i,
                "name": name,
                "util_percent": util_percent,
                "memory_total": memory_total,
                "memory_used": memory_used,
                "memory_util_percent": memory_util_percent,
                "frequency_mhz": freq
            }
            
            if get_monitor_config("gpu", "collect_temp"):
                gpu_data["temperature_c"] = temperature
                
            if get_monitor_config("gpu", "collect_power"):
                gpu_data["power_w"] = power
            
            result.append(gpu_data)
            
    except Exception as e:  # pylint: disable=broad-except
        logger.error("采集 NVIDIA GPU 指标时出错: %s", e)
        
    return result


def _get_amd_card_paths() -> List[str]:
    """获取所有 AMD 显卡的 sysfs 路径。"""
    try:
        base = "/sys/class/drm"
        cards = []
        for entry in os.listdir(base):
            if entry.startswith("card") and not entry.endswith("card"):  # 排除 renderD* 等
                card_path = os.path.join(base, entry)
                # 检查是否是 AMD 显卡
                vendor_path = os.path.join(card_path, "device/vendor")
                if os.path.exists(vendor_path):
                    with open(vendor_path, "r") as f:
                        vendor = f.read().strip()
                        if vendor == "0x1002":  # AMD vendor ID
                            cards.append(card_path)
        return cards
    except Exception as e:  # pylint: disable=broad-except
        logger.error("查找 AMD 显卡失败: %s", e)
        return []


def _read_amd_sysfs(card_path: str, sub_path: str) -> Optional[str]:
    """从 AMD GPU sysfs 读取指标。"""
    try:
        pattern = os.path.join(card_path, sub_path)
        # 支持通配符 *，只读取第一个匹配文件
        for full_path in glob.glob(pattern):
            if os.path.isfile(full_path):
                with open(full_path, "r") as f:
                    return f.read().strip()
    except Exception:  # pylint: disable=broad-except
        pass
    return None


def _read_radeontop(gpu_idx: int) -> Optional[Dict[str, Any]]:
    """使用 radeontop 采集单块 AMD GPU 指标，需 root 或 udev 权限。

返回示例 dict：
{
  "gpu": 12.5,         # core 利用率百分比
  "mem": 4.3,          # 显存占用百分比（radeontop <=1.4 为 'vram', 新版 'mem')
  "sclk": 800.0,       # 核心频率 MHz
  "mclk": 1500.0       # 显存频率 MHz
}
"""
    if not shutil.which("radeontop"):
        return None
    try:
        def _run(cmd_list):
            return subprocess.check_output(cmd_list, text=True, stderr=subprocess.STDOUT)

        # 优先尝试 JSON 输出（radeontop >=1.4 支持 -j）
        base_cmd = ["radeontop", "-d", "-", "-l", "1"]
        cmd_json = base_cmd + ["-j"]
        # 若指定 card 节点存在则附加 -p
        card_path = f"/dev/dri/card{gpu_idx}"
        if os.path.exists(card_path):
            cmd_json += ["-p", card_path]
        try_json = True
        try:
            output = _run(cmd_json)
        except subprocess.CalledProcessError as exc:
            # 旧版不支持 -j，回退普通输出
            output = exc.output or ""
            if "无效的选项" in output or "invalid option" in output:
                try_json = False
            else:
                raise
        if not try_json:
            cmd_plain = base_cmd
            if os.path.exists(card_path):
                cmd_plain += ["-p", card_path]
            output = _run(cmd_plain)

        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            # 1) 先尝试 JSON
            try:
                data = json.loads(line)
                return data
            except json.JSONDecodeError:
                pass
            # 2) 解析两种文本格式
            kvs = {}
            # 2.a  key=value%
            for seg in line.split(';'):
                if '=' in seg:
                    key, val = seg.split('=', 1)
                    key = key.strip()
                    val = val.strip().rstrip('%')
                    try:
                        kvs[key] = float(val)
                    except ValueError:
                        continue
            if kvs:
                return kvs
            # 2.b  radeontop 默认文本: "gpu 12.00%, vram 3.00% 123mb, sclk 20.00% 1.50ghz"
            kvs2 = {}
            for seg in line.split(','):
                seg = seg.strip()
                if not seg:
                    continue
                parts = seg.split()
                if len(parts) >= 2 and parts[1].endswith('%'):
                    key = parts[0]
                    try:
                        kvs2[key] = float(parts[1].rstrip('%'))
                    except ValueError:
                        pass
                    # vram 行同时包含已用 MB
                    if key in ("vram", "mem") and len(parts) >= 3 and parts[2].lower().endswith("mb"):
                        try:
                            mb_val = float(parts[2][:-2])
                            kvs2[key + "_used_mb"] = mb_val
                        except ValueError:
                            pass
                # 频率行: sclk 16.67% 0.150ghz -> 提取 ghz value
                if parts[0] in ("sclk", "mclk") and len(parts) >= 3 and parts[2].lower().endswith("ghz"):
                    try:
                        ghz_val = float(parts[2][:-3])  # 去掉 ghz
                        kvs2[parts[0] + "_ghz"] = ghz_val
                    except ValueError:
                        pass
            if kvs2:
                return kvs2
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("调用 radeontop 失败: %s", exc)
    return None


def _collect_amd() -> List[Dict[str, Any]]:
    """采集 AMD GPU 指标。仅支持Linux。"""
    system = platform.system().lower()
    if system != "linux":
        logger.debug("AMD GPU 监控仅支持 Linux 系统")
        return []

    result = []
    cards = _get_amd_card_paths()

    for i, card_path in enumerate(cards):
        try:
            # 获取设备名称
            name = _read_amd_sysfs(card_path, "device/product_name")
            if not name:
                name = f"AMD-GPU-{i}"
            
            # 基本数据结构
            gpu_data = {
                "vendor": "amd",
                "index": i,
                "name": name,
                "util_percent": 0,  # 兼容服务端，用0代替None
                "memory_total": 0,   # 兼容服务端，用0代替None
                "memory_used": 0,    # 兼容服务端，用0代替None
                "memory_util_percent": 0,  # 兼容服务端，用0代替None
                "frequency_mhz": 0    # 兼容服务端，用0代替None
            }
            
            # 获取频率
            freq = _read_amd_sysfs(card_path, "device/pp_dpm_sclk")
            if freq:
                # 解析当前频率，格式类似：0: 300MHz 1: 2000MHz *
                match = re.search(r"(\d+)MHz \*", freq)
                if match:
                    gpu_data["frequency_mhz"] = int(match.group(1))
            
            # 读取显存信息
            mem_total_str = _read_amd_sysfs(card_path, "device/mem_info_vram_total")
            if mem_total_str:
                try:
                    gpu_data["memory_total"] = int(mem_total_str)
                except ValueError:
                    pass
            mem_used_str = _read_amd_sysfs(card_path, "device/mem_info_vram_used")
            if mem_used_str:
                try:
                    gpu_data["memory_used"] = int(mem_used_str)
                    if gpu_data["memory_total"]:
                        gpu_data["memory_util_percent"] = gpu_data["memory_used"] / gpu_data["memory_total"] * 100
                except ValueError:
                    pass

            # 如果 util_percent 仍为 0，尝试用 radeontop 获取
            if gpu_data.get("util_percent", 0) == 0:
                rt = _read_radeontop(i)
                if rt and ("gpu" in rt or "gpu%" in rt):
                    try:
                        gpu_data["util_percent"] = float(rt.get("gpu", rt.get("gpu%", 0)))  # radeontop 中字段名可能为 gpu
                    except (ValueError, TypeError):
                        pass
                if rt:
                    # 显存利用率
                    if ("mem" in rt or "vram" in rt) and gpu_data.get("memory_util_percent", 0) == 0:
                        try:
                            gpu_data["memory_util_percent"] = float(rt.get("mem", rt.get("vram", 0)))
                        except (ValueError, TypeError):
                            pass
                    # 频率 MHz
                    if gpu_data.get("frequency_mhz", 0) == 0 and "sclk_ghz" in rt:
                        try:
                            gpu_data["frequency_mhz"] = int(rt["sclk_ghz"] * 1000)
                        except (ValueError, TypeError):
                            pass
                    # 显存总量 / 已用
                    if ("vram_used_mb" in rt or "mem_used_mb" in rt) and gpu_data.get("memory_total", 0) == 0:
                        used_mb = rt.get("vram_used_mb", rt.get("mem_used_mb"))
                        percent = gpu_data.get("memory_util_percent", 0)
                        if used_mb is not None and percent > 0:
                            gpu_data["memory_used"] = int(used_mb * 1024 * 1024)
                            gpu_data["memory_total"] = int(gpu_data["memory_used"] * 100 / percent)
            
            # 获取温度
            if get_monitor_config("gpu", "collect_temp"):
                temp = _read_amd_sysfs(card_path, "device/hwmon/hwmon*/temp1_input")
                if temp:
                    gpu_data["temperature_c"] = int(temp) / 1000.0
            
            # 获取功耗
            if get_monitor_config("gpu", "collect_power"):
                power = _read_amd_sysfs(card_path, "device/hwmon/hwmon*/power1_average")
                if power:
                    gpu_data["power_w"] = int(power) / 1000000.0  # 微瓦转瓦
            
            # 获取利用率和显存（需要 rocm-smi）
            try:
                output = subprocess.check_output(
                    ["rocm-smi", "-d", str(i), "--showuse", "--showmemuse"],
                    text=True,
                    stderr=subprocess.DEVNULL
                )
                for line in output.splitlines():
                    if "GPU use (%)" in line:
                        util = re.search(r"(\d+)", line)
                        if util:
                            gpu_data["util_percent"] = int(util.group(1))
                    elif "GPU memory use (%)" in line:
                        mem_util = re.search(r"(\d+)", line)
                        if mem_util:
                            gpu_data["memory_util_percent"] = int(mem_util.group(1))
            except Exception:  # pylint: disable=broad-except
                pass
            
            result.append(gpu_data)
            
        except Exception as e:  # pylint: disable=broad-except
            logger.error("采集 AMD GPU %d 指标时出错: %s", i, e)
            
    return result


def collect() -> List[Dict[str, Any]]:
    """采集所有 GPU 相关指标。"""
    if not get_monitor_config("gpu", "enabled"):
        return []

    result = []
    
    # 采集 NVIDIA GPU
    if NVML_INITIALIZED:
        result.extend(_collect_nvidia())
    
    # 采集 AMD GPU
    result.extend(_collect_amd())
    
    return result