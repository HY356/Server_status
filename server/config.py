"""服务端配置。"""

import os

# 客户端应携带的 Token
TOKEN = "secret-token"

# 监听地址与端口
auth = None
HOST = "0.0.0.0"
PORT = 8045 

# MySQL 连接信息（从环境变量读取）
MYSQL = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "server_status"),
    "charset": "utf8mb4",
} 

SERVER_SECRET_KEY = "why_20250730_secure_key" 