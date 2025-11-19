"""生成并缓存客户端唯一标识 (UUID) 和认证 Token。"""

import base64
import hashlib
import hmac
import platform
import subprocess
from pathlib import Path
import uuid

from .config import SERVER_SECRET_KEY

_ID_FILE = Path("client_id.txt")


def generate_token(uuid_str: str) -> str:
    """使用与服务端相同的算法生成认证 Token。
    
    Args:
        uuid_str: 客户端 UUID
        
    Returns:
        base64 编码的 HMAC token
    """
    secret = SERVER_SECRET_KEY.encode('utf-8')
    h = hmac.new(secret, uuid_str.encode('utf-8'), hashlib.sha256)
    token = base64.urlsafe_b64encode(h.digest()).decode('utf-8').rstrip('=')
    return token


def get_client_id() -> str:
    """返回本机唯一 ID，如文件不存在或为空则生成并写入。"""
    if _ID_FILE.exists():
        content = _ID_FILE.read_text().strip()
        if content:  # 检查文件内容是否为空
            return content

    # 文件不存在或为空，生成新的UUID
    cid = str(uuid.uuid4())
    _ID_FILE.write_text(cid)
    return cid


def get_auth_token() -> str:
    """返回基于 UUID 生成的认证 Token。"""
    return generate_token(get_client_id())


def get_os_info() -> str:
    """获取详细的操作系统信息。

    Returns:
        str: 格式化的操作系统信息，如 "Windows 11 Pro 22H2" 或 "Ubuntu 20.04.3 LTS"
    """
    try:
        system = platform.system()

        if system == "Windows":
            return _get_windows_os_info()
        elif system == "Linux":
            return _get_linux_os_info()
        elif system == "Darwin":  # macOS
            return _get_macos_os_info()
        else:
            # 其他系统，返回基本信息
            return f"{system} {platform.release()}"

    except Exception:
        # 如果获取详细信息失败，返回基本信息
        return f"{platform.system()} {platform.release()}"


def _get_windows_os_info() -> str:
    """获取Windows详细版本信息"""
    try:
        # 使用PowerShell获取详细的Windows版本信息
        cmd = '''
        $os = Get-WmiObject -Class Win32_OperatingSystem
        $version = [System.Environment]::OSVersion.Version
        $release = ""

        # 判断Windows版本
        if ($version.Major -eq 10) {
            if ($version.Build -ge 22000) {
                $winVersion = "Windows 11"
            } else {
                $winVersion = "Windows 10"
            }

            # 获取版本号（如22H2）
            $releaseId = (Get-ItemProperty "HKLM:SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion" -Name DisplayVersion -ErrorAction SilentlyContinue).DisplayVersion
            if ($releaseId) {
                $release = $releaseId
            } else {
                $releaseId = (Get-ItemProperty "HKLM:SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion" -Name ReleaseId -ErrorAction SilentlyContinue).ReleaseId
                if ($releaseId) {
                    $release = $releaseId
                }
            }
        } else {
            $winVersion = $os.Caption
        }

        # 获取版本类型（Pro, Home等）
        $edition = $os.Caption -replace "Microsoft ", "" -replace "Windows ", ""
        if ($edition -match "(Pro|Home|Enterprise|Education)") {
            $editionType = $matches[1]
        } else {
            $editionType = ""
        }

        # 组合最终字符串
        $result = $winVersion
        if ($editionType) {
            $result += " $editionType"
        }
        if ($release) {
            $result += " $release"
        }

        $result
        '''

        result = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

    except Exception:
        pass

    # 备用方法
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            product_name = winreg.QueryValueEx(key, "ProductName")[0]
            try:
                display_version = winreg.QueryValueEx(key, "DisplayVersion")[0]
                return f"{product_name} {display_version}"
            except FileNotFoundError:
                try:
                    release_id = winreg.QueryValueEx(key, "ReleaseId")[0]
                    return f"{product_name} {release_id}"
                except FileNotFoundError:
                    return product_name
    except Exception:
        pass

    # 最后的备用方法
    return f"Windows {platform.release()}"


def _get_linux_os_info() -> str:
    """获取Linux发行版信息"""
    try:
        # 尝试读取 /etc/os-release
        with open("/etc/os-release", "r") as f:
            lines = f.readlines()

        os_info = {}
        for line in lines:
            if "=" in line:
                key, value = line.strip().split("=", 1)
                os_info[key] = value.strip('"')

        # 构建版本字符串
        name = os_info.get("PRETTY_NAME", os_info.get("NAME", "Linux"))
        if name != os_info.get("NAME", ""):
            return name

        version = os_info.get("VERSION", os_info.get("VERSION_ID", ""))
        if version:
            return f"{name} {version}"
        else:
            return name

    except Exception:
        pass

    # 备用方法：尝试 lsb_release
    try:
        result = subprocess.run(
            ["lsb_release", "-d"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            description = result.stdout.strip()
            if description.startswith("Description:"):
                return description.split(":", 1)[1].strip()
            return description
    except Exception:
        pass

    # 最后的备用方法
    return f"Linux {platform.release()}"


def _get_macos_os_info() -> str:
    """获取macOS版本信息"""
    try:
        # 使用sw_vers命令获取macOS版本信息
        result = subprocess.run(
            ["sw_vers"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            info = {}
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    info[key.strip()] = value.strip()

            product_name = info.get('ProductName', 'macOS')
            product_version = info.get('ProductVersion', '')
            build_version = info.get('BuildVersion', '')

            if product_version:
                result_str = f"{product_name} {product_version}"
                if build_version:
                    result_str += f" ({build_version})"
                return result_str
            else:
                return product_name

    except Exception:
        pass

    # 备用方法
    return f"macOS {platform.mac_ver()[0]}"