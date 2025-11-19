"""
客户端时间配置
所有时间相关的参数都在这里统一管理
"""

# ================================
# 网络请求超时配置
# ================================

# HTTP请求超时时间（秒）
HTTP_TIMEOUT = 30

# 注册请求超时时间（秒）
REGISTER_TIMEOUT = 30


# ================================
# 重试间隔配置
# ================================

# 注册被拒绝后重试间隔（秒）
REGISTER_REJECTED_RETRY_INTERVAL = 30 * 60  # 30分钟

# 错误状态检测后等待时间（秒）
ERROR_STATE_RETRY_INTERVAL = 5

# 注册失败后重试间隔（秒）
REGISTER_FAILED_RETRY_INTERVAL = 30

# 服务器未启用监控后重试间隔（秒）
SERVER_INACTIVE_RETRY_INTERVAL = 60

# 配置不完整后重试间隔（秒）
CONFIG_INCOMPLETE_RETRY_INTERVAL = 30


# ================================
# 删除重新初始化配置
# ================================

# 智能休眠重注册间隔配置（秒）
SLEEP_RETRY_INTERVALS = {
    0: 0,      # 第1次：立即重试
    1: 60,     # 第2次：1分钟后重试
    2: 120,    # 第3次：2分钟后重试
    "default": 300  # 第4次及以后：5分钟后重试
}

# 获取休眠重注册间隔的函数
def get_sleep_retry_interval(retry_count: int) -> int:
    """根据重试次数获取休眠间隔"""
    return SLEEP_RETRY_INTERVALS.get(retry_count, SLEEP_RETRY_INTERVALS["default"])


# ================================
# 数据采集和上报配置
# ================================

# 默认数据上报间隔（秒）
DEFAULT_REPORT_INTERVAL = 30

# 缓存数据清理间隔（秒）- 清理超过此时间的数据
CACHE_CLEANUP_INTERVAL = 24 * 60 * 60  # 24小时

# 首次数据发送后等待时间（秒）- 等待一个完整间隔后开始定时采集
FIRST_REPORT_WAIT_INTERVAL = DEFAULT_REPORT_INTERVAL


# ================================
# 硬件采集配置
# ================================

# CPU使用率采集间隔（秒）
CPU_USAGE_SAMPLE_INTERVAL = 1

# CPU使用率采集间隔（测试用，秒）
CPU_USAGE_TEST_INTERVAL = 2

# PowerShell命令超时时间（秒）
POWERSHELL_TIMEOUT = 10

# WMIC命令超时时间（秒）
WMIC_TIMEOUT = 10


# ================================
# 配置验证和默认值
# ================================

def validate_timing_config():
    """验证时间配置的合理性"""
    errors = []
    
    # 检查超时时间
    if HTTP_TIMEOUT <= 0:
        errors.append("HTTP_TIMEOUT 必须大于0")
    
    if REGISTER_TIMEOUT <= 0:
        errors.append("REGISTER_TIMEOUT 必须大于0")
    
    # 检查重试间隔
    if REGISTER_REJECTED_RETRY_INTERVAL < 60:
        errors.append("REGISTER_REJECTED_RETRY_INTERVAL 建议至少60秒")
    
    if ERROR_STATE_RETRY_INTERVAL <= 0:
        errors.append("ERROR_STATE_RETRY_INTERVAL 必须大于0")
    
    # 检查上报间隔
    if DEFAULT_REPORT_INTERVAL <= 0:
        errors.append("DEFAULT_REPORT_INTERVAL 必须大于0")
    
    if CACHE_CLEANUP_INTERVAL <= DEFAULT_REPORT_INTERVAL:
        errors.append("CACHE_CLEANUP_INTERVAL 应该大于 DEFAULT_REPORT_INTERVAL")
    
    return errors


def get_timing_summary():
    """获取时间配置摘要"""
    return {
        "网络超时": {
            "HTTP请求超时": f"{HTTP_TIMEOUT}秒",
            "注册请求超时": f"{REGISTER_TIMEOUT}秒",
        },
        "重试间隔": {
            "注册被拒绝重试": f"{REGISTER_REJECTED_RETRY_INTERVAL//60}分钟",
            "错误状态重试": f"{ERROR_STATE_RETRY_INTERVAL}秒",
            "注册失败重试": f"{REGISTER_FAILED_RETRY_INTERVAL}秒",
            "服务器未启用重试": f"{SERVER_INACTIVE_RETRY_INTERVAL}秒",
            "配置不完整重试": f"{CONFIG_INCOMPLETE_RETRY_INTERVAL}秒",
        },
        "休眠重注册": {
            "第1次重试": f"{get_sleep_retry_interval(0)}秒",
            "第2次重试": f"{get_sleep_retry_interval(1)}秒",
            "第3次重试": f"{get_sleep_retry_interval(2)}秒",
            "第4次及以后": f"{get_sleep_retry_interval(999)}秒",
        },
        "数据采集": {
            "默认上报间隔": f"{DEFAULT_REPORT_INTERVAL}秒",
            "缓存清理间隔": f"{CACHE_CLEANUP_INTERVAL//3600}小时",
            "CPU采集间隔": f"{CPU_USAGE_SAMPLE_INTERVAL}秒",
        },
        "命令超时": {
            "PowerShell超时": f"{POWERSHELL_TIMEOUT}秒",
            "WMIC超时": f"{WMIC_TIMEOUT}秒",
        }
    }


# 在导入时验证配置
_validation_errors = validate_timing_config()
if _validation_errors:
    import logging
    logger = logging.getLogger(__name__)
    for error in _validation_errors:
        logger.warning("时间配置警告: %s", error)
