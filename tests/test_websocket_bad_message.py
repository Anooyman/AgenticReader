"""WebSocket：一条拼坏的 JSON 不该把整条连接打挂。

旧行为：json.loads 的异常冒到连接函数的顶层 except → 发"连接错误"再 close，
前端看到的就是"聊到一半突然断线"，根因却只是这条消息本身坏了。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ui.backend.api import websocket as ws_api


def _app():
    app = FastAPI()
    app.include_router(ws_api.router)
    return app


def test_malformed_message_rejected_connection_survives():
    with TestClient(_app()).websocket_connect("/ws/chat") as ws:
        ws.send_text("{not json at all")
        reply = ws.receive_json()
        assert reply.get("type") == "error"
        assert "JSON" in reply.get("message", "") or "json" in reply.get("message", "")
        # 连接必须还活着：再发一条同样坏的，还能收到第二句拒绝
        ws.send_text("also not json")
        assert ws.receive_json()["type"] == "error"
        ws.close()
