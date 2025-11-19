"""日志管理模块，实现按天滚动的日志文件。"""

import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .config import LOG_DIR, LOG_FORMAT, LOG_DATE_FORMAT, LOG_LEVEL


def setup_logging() -> None:
    """配置日志系统。
    
    - 按天滚动的文件日志
    - 同时输出到控制台
    - 日志格式：时间 级别 消息
    """
    # 确保日志目录存在
    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    
    # 清除已有的处理器
    root_logger.handlers.clear()
    
    # 1. 文件处理器（按天滚动）
    log_file = os.path.join(log_dir, "client.log")
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",          # 每天午夜切换文件
        interval=1,              # 间隔为1天
        backupCount=30,          # 保留30天的日志
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    )
    # 设置滚动日志的命名格式：client.2024-01-30.log
    file_handler.suffix = "%Y-%m-%d.log"
    root_logger.addHandler(file_handler)
    
    # 2. 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    )
    root_logger.addHandler(console_handler)
    
    # 记录启动信息
    logging.info("日志系统初始化完成，日志目录: %s", log_dir)
    

def get_current_log_file() -> str:
    """获取当前日志文件路径。"""
    current_date = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOG_DIR, f"client.{current_date}.log") 