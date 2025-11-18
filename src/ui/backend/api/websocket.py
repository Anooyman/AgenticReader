"""WebSocket路由"""

from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List

from ..config.logging import get_logger
from ..services.chat_service import chat_service

logger = get_logger(__name__)
router = APIRouter()


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket连接建立，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket连接断开，当前连接数: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"发送WebSocket消息失败: {e}")

    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)

        # 清理断开的连接
        for connection in disconnected:
            self.disconnect(connection)


manager = ConnectionManager()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket聊天端点"""
    await manager.connect(websocket)

    try:
        while True:
            # 接收消息
            data = await websocket.receive_json()
            message = data.get("message", "")

            if not message:
                continue

            logger.info(f"收到WebSocket消息: {message[:50]}...")

            # 发送用户消息确认
            timestamp = datetime.now().isoformat()
            await manager.send_personal_message({
                "type": "user_message",
                "content": message,
                "timestamp": timestamp
            }, websocket)

            # 发送处理状态
            await manager.send_personal_message({
                "type": "status",
                "content": "正在思考...",
                "timestamp": datetime.now().isoformat()
            }, websocket)

            try:
                # 检查聊天服务是否已初始化
                chat_status = chat_service.get_status()
                if not chat_status["initialized"]:
                    # 发送错误消息
                    await manager.send_personal_message({
                        "type": "error",
                        "content": "聊天服务未初始化，请先处理文档",
                        "timestamp": datetime.now().isoformat()
                    }, websocket)
                    continue

                # 记录当前ChatService状态用于调试
                logger.info(f"📊 WebSocket处理消息 - 当前ChatService状态: doc_name={chat_status['doc_name']}, reader_type={chat_status['reader_type']}")

                # 调用聊天服务处理消息
                answer = chat_service.chat(message)

                if answer.startswith("❌"):
                    # 发送错误消息
                    await manager.send_personal_message({
                        "type": "error",
                        "content": answer,
                        "timestamp": datetime.now().isoformat()
                    }, websocket)
                else:
                    # 发送AI回复
                    ai_timestamp = datetime.now().isoformat()
                    await manager.send_personal_message({
                        "type": "assistant_message",
                        "content": answer,
                        "timestamp": ai_timestamp
                    }, websocket)

                    logger.info(f"WebSocket LLM回复已发送，长度: {len(answer)}")

            except Exception as e:
                logger.error(f"WebSocket处理聊天失败: {e}")
                # 发送错误消息
                await manager.send_personal_message({
                    "type": "error",
                    "content": f"处理消息时出错: {str(e)}",
                    "timestamp": datetime.now().isoformat()
                }, websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket处理错误: {e}")
        manager.disconnect(websocket)