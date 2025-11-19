"""跨平台兼容性检查模块。"""

import logging
import platform
import subprocess
import sys
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class PlatformChecker:
    """平台兼容性检查器"""
    
    def __init__(self):
        self.system = platform.system().lower()
        self.version = platform.version()
        self.architecture = platform.architecture()[0]
        
    def get_system_info(self) -> Dict[str, str]:
        """获取系统信息"""
        return {
            "system": self.system,
            "version": self.version,
            "architecture": self.architecture,
            "python_version": sys.version,
            "platform": platform.platform()
        }
    
    def check_python_version(self) -> bool:
        """检查Python版本是否满足要求"""
        version_info = sys.version_info
        if version_info.major >= 3 and version_info.minor >= 8:
            logger.info("Python版本检查通过: %s", sys.version)
            return True
        else:
            logger.error("Python版本过低，需要Python 3.8+，当前版本: %s", sys.version)
            return False
    
    def check_required_modules(self) -> Dict[str, bool]:
        """检查必需的Python模块"""
        required_modules = {
            "psutil": "系统信息采集",
            "requests": "HTTP请求",
            "pynvml": "NVIDIA GPU监控"
        }
        
        results = {}
        for module, description in required_modules.items():
            try:
                __import__(module)
                results[module] = True
                logger.info("模块 %s (%s) 可用", module, description)
            except ImportError:
                results[module] = False
                logger.error("模块 %s (%s) 不可用", module, description)
        
        return results
    
    def check_system_commands(self) -> Dict[str, bool]:
        """检查系统命令可用性"""
        commands = {}
        
        if self.system == "linux":
            linux_commands = {
                "sensors": "CPU温度和功耗监控",
                "lshw": "硬件信息查询",
                "lsblk": "磁盘信息查询",
                "radeontop": "AMD GPU监控（可选）",
                "rocm-smi": "AMD GPU监控（可选）"
            }
            commands.update(linux_commands)
        
        elif self.system == "windows":
            # Windows特定命令（如果有的话）
            pass
        
        elif self.system == "darwin":  # macOS
            macos_commands = {
                "sysctl": "系统信息查询"
            }
            commands.update(macos_commands)
        
        results = {}
        for cmd, description in commands.items():
            try:
                subprocess.run([cmd, "--version"], 
                             capture_output=True, 
                             timeout=5, 
                             check=False)
                results[cmd] = True
                logger.info("命令 %s (%s) 可用", cmd, description)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                results[cmd] = False
                if cmd in ["radeontop", "rocm-smi"]:
                    logger.debug("可选命令 %s (%s) 不可用", cmd, description)
                else:
                    logger.warning("命令 %s (%s) 不可用", cmd, description)
        
        return results
    
    def check_gpu_support(self) -> Dict[str, bool]:
        """检查GPU监控支持"""
        results = {
            "nvidia": False,
            "amd": False
        }
        
        # 检查NVIDIA支持
        try:
            import pynvml
            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()
            results["nvidia"] = device_count > 0
            logger.info("NVIDIA GPU支持: %s (%d个设备)", 
                       "是" if results["nvidia"] else "否", device_count)
        except Exception as e:
            logger.debug("NVIDIA GPU检查失败: %s", e)
        
        # 检查AMD支持（仅Linux）
        if self.system == "linux":
            try:
                import os
                drm_path = "/sys/class/drm"
                if os.path.exists(drm_path):
                    amd_cards = []
                    for entry in os.listdir(drm_path):
                        if entry.startswith("card"):
                            vendor_path = os.path.join(drm_path, entry, "device/vendor")
                            if os.path.exists(vendor_path):
                                with open(vendor_path, "r") as f:
                                    if f.read().strip() == "0x1002":  # AMD vendor ID
                                        amd_cards.append(entry)
                    results["amd"] = len(amd_cards) > 0
                    logger.info("AMD GPU支持: %s (%d个设备)", 
                               "是" if results["amd"] else "否", len(amd_cards))
            except Exception as e:
                logger.debug("AMD GPU检查失败: %s", e)
        
        return results
    
    def get_platform_limitations(self) -> List[str]:
        """获取当前平台的限制"""
        limitations = []
        
        if self.system == "windows":
            limitations.extend([
                "CPU功耗监控不支持",
                "内存频率监控不支持", 
                "磁盘型号获取不支持",
                "AMD GPU监控不支持"
            ])
        
        elif self.system == "darwin":  # macOS
            limitations.extend([
                "CPU功耗监控不支持",
                "内存频率监控不支持",
                "磁盘型号获取不支持", 
                "AMD GPU监控不支持"
            ])
        
        elif self.system == "linux":
            # Linux支持最全面，检查具体命令
            cmd_results = self.check_system_commands()
            if not cmd_results.get("sensors", False):
                limitations.append("CPU温度和功耗监控不可用（缺少sensors命令）")
            if not cmd_results.get("lshw", False):
                limitations.append("内存频率监控不可用（缺少lshw命令）")
            if not cmd_results.get("lsblk", False):
                limitations.append("磁盘型号获取不可用（缺少lsblk命令）")
        
        return limitations
    
    def run_full_check(self) -> Dict[str, any]:
        """运行完整的兼容性检查"""
        logger.info("开始平台兼容性检查...")
        
        results = {
            "system_info": self.get_system_info(),
            "python_version_ok": self.check_python_version(),
            "required_modules": self.check_required_modules(),
            "system_commands": self.check_system_commands(),
            "gpu_support": self.check_gpu_support(),
            "limitations": self.get_platform_limitations()
        }
        
        # 总结
        all_modules_ok = all(results["required_modules"].values())
        critical_commands_ok = True
        
        if self.system == "linux":
            # Linux下检查关键命令
            critical_commands = ["sensors", "lshw", "lsblk"]
            critical_commands_ok = any(results["system_commands"].get(cmd, False) 
                                     for cmd in critical_commands)
        
        results["overall_compatible"] = (
            results["python_version_ok"] and 
            all_modules_ok and 
            critical_commands_ok
        )
        
        logger.info("兼容性检查完成，整体兼容性: %s", 
                   "良好" if results["overall_compatible"] else "有问题")
        
        return results


def main():
    """主函数，用于独立运行兼容性检查"""
    logging.basicConfig(level=logging.INFO, 
                       format="%(asctime)s %(levelname)s %(message)s")
    
    checker = PlatformChecker()
    results = checker.run_full_check()
    
    print("\n=== 平台兼容性检查报告 ===")
    print(f"操作系统: {results['system_info']['system']}")
    print(f"架构: {results['system_info']['architecture']}")
    print(f"Python版本: {results['python_version_ok']}")
    print(f"必需模块: {results['required_modules']}")
    print(f"GPU支持: {results['gpu_support']}")
    
    if results['limitations']:
        print("\n功能限制:")
        for limitation in results['limitations']:
            print(f"  - {limitation}")
    
    print(f"\n整体兼容性: {'✓ 良好' if results['overall_compatible'] else '✗ 有问题'}")


if __name__ == "__main__":
    main()
