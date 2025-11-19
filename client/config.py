"""客户端全局配置项。"""

import os

# 服务端地址（用于注册和上报）
BASE_URL = os.getenv("SERVER_URL", "http://localhost:8045")
REGISTER_URL = f"{BASE_URL}/api/agent/register"

# 本地缓存 SQLite 文件路径
DB_PATH = "client_cache.db"

# 单次批量发送的最大条数
SEND_BATCH_SIZE = 20

# HTTP 请求超时时间（秒）- 已移至timing_config.py统一管理
# TIMEOUT = 5  # 已废弃，使用timing_config.HTTP_TIMEOUT

# 服务端共享密钥（从环境变量读取）
SERVER_SECRET_KEY = os.getenv("SERVER_SECRET_KEY", "")

# 默认配置（仅在服务端未指定时使用）
DEFAULT_CONFIG = {
    "status": "accepted",       # 状态（accepted/rejected/pending）
    "server_id": None,         # 服务器ID（由服务端分配）
    "is_active": True,         # 是否启用监控
    "report_interval": 30,     # 上报间隔（秒）
    "monitor_items": {         # 监控项配置
        "cpu": {
            "enabled": True,   # 是否监控 CPU
            "collect_temp": True, # 是否采集温度
            "collect_power": True # 是否采集功耗
        },
        "memory": {
            "enabled": True    # 是否监控内存
        },
        "disk": {
            "enabled": True,   # 是否监控磁盘
            "paths": []        # 要监控的路径，空列表表示监控所有主要分区
        },
        "gpu": {
            "enabled": True,   # 是否监控 GPU
            "collect_temp": True, # 是否采集温度
            "collect_power": True # 是否采集功耗
        }
    },
    "monitor_config": {        # 监控模式配置
        "mode": "CONTINUOUS",  # 监控模式：CONTINUOUS/SCHEDULED/COUNTDOWN
        "schedule": {},        # 定时监控配置
        "countdown": {}        # 倒计时监控配置
    },
    "report_url": f"{BASE_URL}/api/agent/report",
}

# 运行时配置（将被服务端配置覆盖）
RUNTIME_CONFIG = DEFAULT_CONFIG.copy()

# API 配置
API_ENDPOINT = RUNTIME_CONFIG["report_url"]
AUTH_TOKEN = None  # 将在运行时由主程序设置

# 监控配置（从 RUNTIME_CONFIG 中读取）
def get_monitor_config(item: str, field: str = "enabled") -> bool:
    """获取监控项配置。"""
    try:
        return RUNTIME_CONFIG["monitor_items"][item][field]
    except KeyError:
        return DEFAULT_CONFIG["monitor_items"][item][field]

def get_disk_paths() -> list:
    """获取需要监控的磁盘路径。

    新版本服务端不再返回paths字段，客户端使用固定路径或自动检测。
    """
    try:
        # 尝试从运行时配置获取paths
        return RUNTIME_CONFIG["monitor_items"]["disk"]["paths"]
    except KeyError:
        try:
            # 尝试从默认配置获取paths
            return DEFAULT_CONFIG["monitor_items"]["disk"]["paths"]
        except KeyError:
            # 如果都没有paths字段，返回默认路径
            # 新版本服务端简化了磁盘监控配置，不再包含paths字段
            import platform
            system = platform.system().lower()
            if system == "windows":
                return ["C:\\"]  # Windows默认监控C盘
            else:
                return ["/"]     # Linux/macOS默认监控根目录

def get_report_interval() -> int:
    """获取上报间隔。"""
    return RUNTIME_CONFIG.get("report_interval", DEFAULT_CONFIG["report_interval"])

def get_monitor_mode_config() -> dict:
    """获取监控模式配置。"""
    try:
        return RUNTIME_CONFIG.get("monitor_config", DEFAULT_CONFIG["monitor_config"])
    except KeyError:
        return DEFAULT_CONFIG["monitor_config"]

def is_monitoring_enabled() -> bool:
    """检查是否启用了任何监控项。"""
    try:
        monitor_items = RUNTIME_CONFIG.get("monitor_items", DEFAULT_CONFIG["monitor_items"])
        for item_config in monitor_items.values():
            if isinstance(item_config, dict) and item_config.get("enabled", False):
                return True
        return False
    except Exception:
        return True  # 出错时默认允许监控

def is_server_active() -> bool:
    """检查服务器是否启用监控。"""
    return RUNTIME_CONFIG.get("is_active", DEFAULT_CONFIG["is_active"])

# 状态管理配置
AUTO_RESET_ERROR_STATE_ON_STARTUP = True  # 启动时自动重置错误状态
AUTO_RESET_REGISTERING_STATE_ON_STARTUP = True  # 启动时自动重置注册中状态

# 调试配置
PRINT_METRICS = True

# 日志配置
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_LEVEL = "INFO"