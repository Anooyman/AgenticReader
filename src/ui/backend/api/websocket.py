"""WebSocket 路由"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
from datetime import datetime

router = APIRouter()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket 聊天端点"""
    await websocket.accept()
    print("✅ WebSocket 连接已建立")

    try:
        from ..services.chat_service import chat_service

        while True:
            # 接收消息
            data = await websocket.receive_text()
            message_data = json.loads(data)

            message_type = message_data.get("type")
            user_message = message_data.get("message")

            if message_type == "user_message" and user_message:
                # 回显用户消息
                await websocket.send_json({
                    "type": "user_message",
                    "content": user_message,
                    "timestamp": datetime.now().isoformat()
                })

                # 发送状态
                await websocket.send_json({
                    "type": "status",
                    "content": "正在处理..."
                })

                try:
                    # 调用聊天服务
                    response = await chat_service.chat(user_message)

                    # 发送回复
                    await websocket.send_json({
                        "type": "assistant_message",
                        "content": response.get("answer", "抱歉，我无法回答这个问题。"),
                        "references": response.get("references", []),
                        "timestamp": datetime.now().isoformat()
                    })

                except Exception as e:
                    print(f"❌ 聊天处理失败: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "content": f"处理失败: {str(e)}"
                    })

    except WebSocketDisconnect:
        print("🔌 WebSocket 连接已断开")
    except Exception as e:
        print(f"❌ WebSocket 错误: {e}")
        try:
            await websocket.close()
        except:
            pass
