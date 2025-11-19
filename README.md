# 🖥️ Server Status Monitor

> 一个轻量级、易用的分布式服务器监控系统

想象一下，你有多台服务器分散在不同的地方，你需要随时了解它们的运行状态。这个项目就是为了解决这个问题而生的。

## ✨ 核心功能

你可以用它来做什么？

- 📊 **实时监控**：自动采集服务器的 CPU、内存、磁盘、GPU 等关键指标
- 🌐 **一站式管理**：一个服务端就能管理多个客户端，轻松扩展
- ⚙️ **灵活配置**：根据需要动态调整监控项、上报频率等参数
- 🔐 **安全可靠**：内置 Token 认证机制，只有授权的客户端才能上报数据
- ✅ **审核机制**：新客户端需要管理员审核通过才能开始监控
- 📝 **完整日志**：记录所有服务器事件和性能指标，便于问题排查
- 🔑 **环境变量管理**：敏感信息不再硬编码，安全上传到 GitHub

## 📁 项目结构一览

```
Server_status/
├── server/                 # 🖥️ 服务端（中央监控中心）
│   ├── main.py            # Flask 应用，处理所有请求
│   ├── config.py          # 配置文件（数据库、密钥等）
│   └── db.py              # 数据库操作（MySQL）
│
├── client/                # 💻 客户端（部署在被监控的服务器上）
│   ├── main.py            # 客户端入口，启动监控
│   ├── config.py          # 客户端配置
│   ├── collector/         # 指标采集（CPU、内存、磁盘、GPU）
│   ├── sender.py          # 负责上报数据到服务端
│   ├── cache.py           # 本地缓存，避免数据丢失
│   ├── identity.py        # 客户端身份管理（UUID）
│   ├── logger.py          # 日志记录
│   ├── state_manager.py   # 状态管理（注册、运行等）
│   ├── heartbeat.py       # 心跳机制（保活）
│   ├── monitor_config.py  # 监控配置管理
│   ├── platform_check.py  # 平台检测（Windows/Linux/macOS）
│   └── timing_config.py   # 时间相关配置
│
├── logs/                  # 📋 日志目录（运行时生成）
├── requirements.txt       # 📦 Python 依赖列表
├── .env.example          # 🔑 环境变量示例（复制后改名为 .env）
├── .gitignore            # 🚫 Git 忽略文件
└── README.md             # 📖 本文件
```

## 🚀 快速开始

### 📋 前置要求

在开始之前，请确保你的系统中已安装：

- **Python 3.7+** - 运行环境
- **MySQL 5.7+** 或 **MariaDB** - 数据存储
- **Linux/Windows/macOS** - 操作系统（都支持）

### 📦 第一步：安装依赖

克隆项目后，进入项目目录，运行：

```bash
pip install -r requirements.txt
```

这会安装所有必要的 Python 库。

### 🔑 第二步：配置环境变量

1. **复制环境变量模板**
   ```bash
   cp .env.example .env
   ```

2. **编辑 `.env` 文件，填入你的配置**

   **服务端配置** (在服务端机器上)：
   ```bash
   # 数据库配置
   DB_HOST=localhost          # MySQL 地址
   DB_PORT=3306               # MySQL 端口
   DB_USER=root               # MySQL 用户
   DB_PASSWORD=your_password  # MySQL 密码
   DB_NAME=server_status      # 数据库名称
   
   # 安全密钥（自定义，要记住！）
   SERVER_SECRET_KEY=my_secret_key_12345
   ```

   **客户端配置** (在被监控的服务器上)：
   ```bash
   # 服务端地址（指向你的服务端机器）
   SERVER_URL=http://your_server_ip:8045
   
   # 安全密钥（必须与服务端相同！）
   SERVER_SECRET_KEY=my_secret_key_12345
   ```

### 🖥️ 第三步：启动服务端

在服务端机器上运行：

```bash
python -m server.main
```

你会看到类似的输出：
```
 * Running on http://0.0.0.0:8045
 * WARNING: This is a development server. Do not use it in production.
```

服务端现在已启动，监听 `8045` 端口。

### 💻 第四步：启动客户端

在被监控的服务器上运行：

```bash
python -m client.main
```

客户端会自动执行以下步骤：

1. ✅ 生成唯一的客户端 ID（UUID）
2. 📤 向服务端注册
3. ⏳ 等待管理员审核（此时不会采集数据）
4. ✨ 审核通过后自动开始采集和上报指标

### 👨‍💼 第五步：管理员审核

作为管理员，你需要审核新注册的客户端。

**查看待审核的客户端**：
```bash
curl http://localhost:8045/api/admin/servers/pending
```

**接受客户端注册**：
```bash
curl -X POST http://localhost:8045/api/admin/servers/1/accept
```

**拒绝客户端注册**：
```bash
curl -X POST http://localhost:8045/api/admin/servers/1/reject \
  -H "Content-Type: application/json" \
  -d '{"reason": "不符合要求"}'
```

审核通过后，客户端会自动开始上报数据！

## 📡 API 文档

> 这部分是给开发者看的。如果你只是想用这个系统，可以跳过这部分。

### 1️⃣ 客户端注册接口

当客户端第一次启动时，会向服务端发送注册请求。

**请求示例**
```bash
curl -X POST http://localhost:8045/api/agent/register \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "550e8400-e29b-41d4-a716-446655440000",
    "hostname": "my-server",
    "os": "Linux"
  }'
```

**成功响应** (状态待审核)
```json
{
  "status": "pending",
  "message": "注册请求正在等待审核"
}
```

**成功响应** (审核通过)
```json
{
  "status": "accepted",
  "server_id": 1,
  "auth_token": "abc123def456...",
  "report_url": "http://localhost:8045/api/agent/report",
  "report_interval": 30,
  "monitor_cpu": true,
  "monitor_memory": true,
  "monitor_disks": null,
  "monitor_gpu": true,
  "is_active": true
}
```

### 2️⃣ 上报指标接口

客户端每 30 秒会将采集的指标上报到服务端。

**请求示例**
```bash
curl -X POST http://localhost:8045/api/agent/report \
  -H "X-Auth-Token: abc123def456..." \
  -H "Content-Type: application/json" \
  -d '[{
    "client_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2025-01-15T10:30:45Z",
    "cpu": {
      "usage_percent": 45.5,
      "temperature_c": 65.0,
      "power_w": 25.3
    },
    "memory": {
      "percent": 60.5,
      "used": 8589934592,
      "total": 16777216000,
      "frequency_mhz": 3200
    },
    "disk": [{
      "device": "sda1",
      "mountpoint": "/",
      "percent": 75.5,
      "used": 214748364800,
      "total": 268435456000
    }],
    "gpus": [{
      "name": "NVIDIA RTX 3090",
      "index": 0,
      "util_percent": 85.5,
      "memory_util_percent": 90.0,
      "power_w": 320.5
    }]
  }]'
```

**成功响应**
```json
{
  "status": "ok",
  "received": 1
}
```

### 3️⃣ 管理员接口

#### 查看待审核的客户端

```bash
curl http://localhost:8045/api/admin/servers/pending
```

返回所有状态为 `PENDING` 的客户端列表。

#### 接受客户端注册

```bash
curl -X POST http://localhost:8045/api/admin/servers/1/accept
```

客户端会立即收到 `auth_token`，开始上报数据。

#### 拒绝客户端注册

```bash
curl -X POST http://localhost:8045/api/admin/servers/1/reject \
  -H "Content-Type: application/json" \
  -d '{"reason": "不符合安全要求"}'
```

客户端会收到拒绝通知，停止尝试注册。

## 📊 监控项详解

系统会自动采集以下指标，你可以根据需要选择启用或禁用。

### 🔴 CPU 监控

监控服务器的处理器使用情况。

- **使用率百分比** - CPU 当前被占用的百分比（0-100%）
- **温度** - CPU 核心温度（摄氏度，某些硬件不支持）
- **功耗** - CPU 当前消耗的功率（瓦特，某些硬件不支持）

### 🟢 内存监控

监控服务器的 RAM 使用情况。

- **使用率百分比** - 内存被占用的百分比（0-100%）
- **已用内存** - 当前使用的内存大小（字节）
- **总内存** - 系统总内存大小（字节）
- **内存频率** - 内存运行频率（MHz）

### 🟡 磁盘监控

监控服务器的存储空间使用情况。

- **设备名称** - 磁盘设备标识（如 `/dev/sda1`）
- **挂载点** - 磁盘挂载路径（如 `/` 或 `C:\`）
- **使用率百分比** - 磁盘被占用的百分比
- **已用空间** - 当前使用的空间大小（字节）
- **总空间** - 磁盘总容量（字节）

### 🔵 GPU 监控

监控 NVIDIA GPU 的使用情况（如果有 GPU）。

- **GPU 名称** - GPU 型号（如 RTX 3090）
- **GPU 索引** - GPU 在系统中的编号
- **利用率百分比** - GPU 计算单元的使用率
- **显存利用率** - GPU 显存的使用率
- **功耗** - GPU 当前消耗的功率（瓦特）

## ⚙️ 配置说明

### 自定义监控项

在 `client/config.py` 中可以启用/禁用特定的监控项：

```python
DEFAULT_CONFIG = {
    "monitor_items": {
        "cpu": {
            "enabled": True,           # 是否监控 CPU
            "collect_temp": True,      # 是否采集温度
            "collect_power": True      # 是否采集功耗
        },
        "memory": {
            "enabled": True            # 是否监控内存
        },
        "disk": {
            "enabled": True,           # 是否监控磁盘
            "paths": []                # 要监控的路径（空列表=所有主要分区）
        },
        "gpu": {
            "enabled": True,           # 是否监控 GPU
            "collect_temp": True,      # 是否采集温度
            "collect_power": True      # 是否采集功耗
        }
    }
}
```

### 上报间隔

- **默认值**：30 秒
- **说明**：客户端每 30 秒采集一次指标并上报到服务端
- **修改方式**：通过服务端数据库修改 `servers` 表的 `report_interval` 字段

## 🔧 故障排除

遇到问题？按照以下步骤排查。

### ❌ 问题：客户端无法连接到服务端

**症状**：客户端启动后一直显示 "连接失败" 或 "连接超时"

**解决步骤**：

1. **检查服务端是否启动**
   ```bash
   # 在服务端机器上检查 8045 端口是否开放
   netstat -an | grep 8045  # Linux/macOS
   netstat -an | findstr 8045  # Windows
   ```

2. **检查 `SERVER_URL` 环境变量**
   ```bash
   echo $SERVER_URL  # Linux/macOS
   echo %SERVER_URL%  # Windows
   ```
   确保指向正确的服务端地址和端口。

3. **检查防火墙**
   - 确保防火墙允许 8045 端口的入站连接
   - 如果跨越网络，确保网络连接正常

### ❌ 问题：注册被拒绝

**症状**：客户端显示 "Registration rejected"

**解决步骤**：

1. **查看待审核列表**
   ```bash
   curl http://localhost:8045/api/admin/servers/pending
   ```

2. **检查是否有拒绝原因**
   - 查看服务端日志了解拒绝原因

3. **重新审核**
   ```bash
   curl -X POST http://localhost:8045/api/admin/servers/1/accept
   ```

### ❌ 问题：指标采集失败

**症状**：客户端启动但没有上报数据

**解决步骤**：

1. **检查客户端日志**
   ```bash
   tail -f logs/client.log  # Linux/macOS
   Get-Content logs/client.log -Tail 20  # Windows
   ```

2. **检查系统权限**
   - 某些指标（如 CPU 温度）需要管理员权限
   - 尝试以管理员身份运行客户端

3. **检查依赖库**
   ```bash
   pip list | grep psutil
   pip list | grep pynvml
   ```
   确保所有依赖都已安装

4. **检查 GPU 驱动**
   - 如果启用了 GPU 监控但没有 NVIDIA GPU，会导致采集失败
   - 在 `client/config.py` 中禁用 GPU 监控

## 📚 依赖库说明

这个项目使用了以下开源库，感谢它们的贡献！

| 库名 | 用途 | 说明 |
|------|------|------|
| **psutil** | 系统指标采集 | 采集 CPU、内存、磁盘等系统信息 |
| **pynvml** | GPU 监控 | 采集 NVIDIA GPU 的使用情况 |
| **requests** | HTTP 客户端 | 客户端用于向服务端发送数据 |
| **flask** | Web 框架 | 服务端 API 框架 |
| **pymysql** | 数据库驱动 | 连接和操作 MySQL 数据库 |

所有依赖都已列在 `requirements.txt` 中，使用 `pip install -r requirements.txt` 即可一键安装。

## 💡 常见问题

**Q: 能否在生产环境中使用？**

A: 当前版本使用 Flask 开发服务器，不建议直接用于生产环境。建议使用 Gunicorn、uWSGI 等生产级 WSGI 服务器。

**Q: 支持哪些操作系统？**

A: 支持 Linux、Windows、macOS。客户端会自动检测操作系统并采用相应的采集方式。

**Q: 数据会被保存多久？**

A: 数据会一直保存在 MySQL 数据库中，你可以根据需要定期清理历史数据。

**Q: 能否修改上报间隔？**

A: 可以。在服务端数据库中修改 `servers` 表的 `report_interval` 字段，客户端会在下次注册时获取新的间隔。

**Q: 如何扩展监控项？**

A: 修改 `client/collector/` 目录下的采集模块，添加新的指标采集逻辑即可。

## 📝 许可证

MIT License - 详见 LICENSE 文件

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

如果你有任何建议或发现了 Bug，请随时提出。让我们一起让这个项目变得更好！

---

**最后更新**：2025 年 1 月

**维护者**：Server Status Monitor 开源社区
