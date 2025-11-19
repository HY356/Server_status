"""服务端主程序。"""

import logging
from typing import Dict, Any, List

from flask import Flask, abort, jsonify, request

from . import db

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# 初始化数据库表
db.init_tables()


@app.route("/api/agent/register", methods=["POST"])
def register():
    """处理客户端注册请求。"""
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        abort(400, "Invalid request body")

    uuid = data.get("client_id")
    hostname = data.get("hostname")
    if not (uuid and hostname):
        abort(400, "Missing client_id or hostname")

    result = db.register_server(uuid, hostname, request.remote_addr)
    return jsonify(result)


@app.route("/api/admin/servers/pending", methods=["GET"])
def list_pending():
    """获取待审核的服务器列表。"""
    servers = db.get_pending_servers()
    return jsonify(servers)


@app.route("/api/admin/servers/<int:server_id>/accept", methods=["POST"])
def accept_server(server_id: int):
    """接受服务器注册。"""
    if db.accept_server(server_id):
        return jsonify({"status": "ok"})
    abort(404, "Server not found")


@app.route("/api/admin/servers/<int:server_id>/reject", methods=["POST"])
def reject_server(server_id: int):
    """拒绝服务器注册。"""
    data = request.get_json(force=True, silent=True) or {}
    reason = data.get("reason", "")
    
    if db.reject_server(server_id, reason):
        return jsonify({"status": "ok"})
    abort(404, "Server not found")


@app.route("/api/agent/report", methods=["POST"])
def report():
    """接收客户端上报的指标列表。"""
    client_token = request.headers.get("X-Auth-Token")
    if not client_token:
        abort(401, "Unauthorized: Invalid token")

    data = request.get_json(force=True, silent=True)
    if not isinstance(data, list):
        abort(400, "Payload must be a JSON array")

    # 验证第一条数据的 client_id
    if not data:
        return jsonify({"status": "ok", "received": 0})

    entry = data[0]
    uuid = entry.get("client_id")
    if not uuid:
        abort(400, "Missing client_id in metrics")

    # 查询该 UUID 对应的认证信息
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT auth_token, register_status FROM servers WHERE uuid = %s",
            (uuid,)
        )
        server = cur.fetchone()
        if not server:
            abort(401, "Unknown client")
        if server["register_status"] != "ACCEPTED":
            abort(403, "Registration not accepted")
        if server["auth_token"] != client_token:
            abort(401, "Invalid token for this client")

    count: int = len(data)
    logging.info("收到 %d 条指标", count)

    for idx, entry in enumerate(data, start=1):
        ts = entry.get("timestamp")

        # 更新心跳时间
        db.update_server_seen(uuid, request.remote_addr)

        cpu: Dict[str, Any] = entry.get("cpu", {})
        mem: Dict[str, Any] = entry.get("memory", {})

        logging.info(
            "[Entry %d] ts=%s | CPU %.1f%%, %.1f°C, %.1fW | Mem %.1f%% (%.2f/%.2f GB) freq=%s MHz",
            idx,
            ts,
            cpu.get("usage_percent", 0.0),
            cpu.get("temperature_c", -1.0) or -1.0,
            cpu.get("power_w", -1.0) or -1.0,
            mem.get("percent", 0.0),
            (mem.get("used", 0) / 1024 ** 3),
            (mem.get("total", 0) / 1024 ** 3),
            mem.get("frequency_mhz", "-") or "-",
        )

        # 打印磁盘信息
        for d in entry.get("disk", []):
            logging.info(
                "    Disk %s at %s %.1f%% used (%.2f/%.2f GB)",
                d.get("device"),
                d.get("mountpoint"),
                d.get("percent"),
                d.get("used", 0) / 1024 ** 3,
                d.get("total", 0) / 1024 ** 3,
            )

        # 打印 GPU 信息
        for g in entry.get("gpus", []):
            logging.info(
                "    GPU %s idx=%s util=%.1f%% mem=%.1f%% power=%.1fW",
                g.get("name"),
                g.get("index"),
                g.get("util_percent"),
                g.get("memory_util_percent"),
                g.get("power_w", -1.0) or -1.0,
            )

    return jsonify({"status": "ok", "received": count}) 