"""WebSocket 路由"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import traceback
from datetime import datetime
from urllib.parse import urlparse
import os

router = APIRouter()

# 检查是否为开发模式
DEBUG_MODE = os.getenv("DEBUG", "false").lower() == "true"

# 本地握手来源校验：只放行回环地址来源
LOCAL_WS_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_allowed_origin(origin: str) -> bool:
    """检查 WebSocket 握手 Origin 是否来自本机回环地址"""
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https", "ws", "wss"):
        return False
    host = (parsed.hostname or "").lower()
    return host in LOCAL_WS_HOSTS


def _cleanup_progress_callbacks(chat_service, session_ids) -> None:
    """连接断开时注销本连接注册过的所有进度回调（chat_service 为共享单例）"""
    if not chat_service or not session_ids:
        return
    for session_id in list(session_ids):
        try:
            chat_service.unregister_progress_callback(session_id)
        except Exception:
            pass


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket 聊天端点"""
    # 握手来源校验：存在 Origin 且非本地来源则拒绝；无 Origin（本地工具/原生客户端）放行
    origin = websocket.headers.get("origin")
    if origin and not _is_allowed_origin(origin):
        print(f"⚠️  已拒绝来自非本地来源的 WebSocket 握手: Origin={origin}")
        await websocket.close(code=4403)
        return

    await websocket.accept()
    print("✅ WebSocket 连接已建立")
    
    # 连接状态标志
    is_connected = True
    # 本连接注册过进度回调的会话ID，连接断开时统一注销，避免残留到共享的
    # chat_service 单例上影响其它会话。
    registered_session_ids = set()
    chat_service = None

    try:
        from ..services.chat_service import chat_service

        while True:
            # 接收消息
            data = await websocket.receive_text()
            message_data = json.loads(data)

            message_type = message_data.get("type")
            user_message = message_data.get("message")
            # 会话ID：前端每条消息都会带上当前会话；缺省时由 chat_service
            # 回退到最近活跃会话，保持向后兼容。
            msg_session_id = message_data.get("session_id")
            # 从消息中提取工具/文档选择（支持每条消息动态切换）
            msg_enabled_tools = message_data.get("enabled_tools")
            msg_selected_docs = message_data.get("selected_docs")

            # 日志记录收到的消息（开发模式下更详细）
            if DEBUG_MODE:
                print(f"📥 收到消息: type={message_type}, session={msg_session_id}, tools={msg_enabled_tools}, docs={msg_selected_docs}")
                print(f"   用户消息: {user_message[:100]}..." if len(user_message or "") > 100 else f"   用户消息: {user_message}")
            else:
                print(f"📥 收到消息: type={message_type}")

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

                # 定义进度回调函数
                async def progress_callback(progress_data):
                    """发送进度更新到客户端"""
                    nonlocal is_connected
                    
                    if not is_connected:
                        # 静默忽略，连接已关闭
                        return
                    
                    try:
                        await websocket.send_json({
                            "type": "progress",
                            **progress_data,
                            "timestamp": datetime.now().isoformat()
                        })
                    except RuntimeError as e:
                        # WebSocket 已关闭，停止发送
                        if "close message has been sent" in str(e):
                            is_connected = False
                        # 不打印错误，避免日志污染
                    except Exception as e:
                        # 其他异常才打印
                        print(f"⚠️  进度更新异常: {type(e).__name__}: {e}")

                try:
                    # 进度回调按会话注册到 chat_service（断开时统一注销），
                    # 这样多个会话并行时进度只会发到各自的连接/会话。
                    if msg_session_id:
                        chat_service.register_progress_callback(msg_session_id, progress_callback)
                        registered_session_ids.add(msg_session_id)

                    # 调用聊天服务（传递进度回调、会话ID和工具/文档选择）
                    response = await chat_service.chat(
                        user_message,
                        progress_callback=progress_callback,
                        enabled_tools=msg_enabled_tools,
                        selected_docs=msg_selected_docs,
                        session_id=msg_session_id
                    )

                    # 本轮结束即注销该会话的回调，避免指向已失效的连接
                    # （见下方 finally）

                    # 发送回复
                    answer_content = response.get("answer", "抱歉，我无法回答这个问题。")
                    answer_length = len(answer_content)

                    # 日志记录回复
                    if DEBUG_MODE:
                        print(f"📤 发送回复: 长度={answer_length}, 引用数={len(response.get('references', []))}")
                    else:
                        print(f"📤 发送回复: 长度={answer_length}")

                    await websocket.send_json({
                        "type": "assistant_message",
                        "content": answer_content,
                        "references": response.get("references", []),
                        "timestamp": datetime.now().isoformat()
                    })

                except Exception as e:
                    # 详细的错误日志
                    error_trace = traceback.format_exc()
                    print(f"❌ 聊天处理失败: {e}")
                    print(f"详细错误堆栈:\n{error_trace}")

                    # 构建错误响应
                    error_message = f"处理失败: {str(e)}"

                    # 开发模式下返回详细堆栈信息
                    if DEBUG_MODE:
                        error_message += f"\n\n调试信息:\n{error_trace}"

                    await websocket.send_json({
                        "type": "error",
                        "content": error_message,
                        "timestamp": datetime.now().isoformat()
                    })

                finally:
                    # 本轮结束（正常或异常）都注销该会话的进度回调，
                    # 防止悬挂的回调继续往本连接里推送进度。
                    if msg_session_id:
                        chat_service.unregister_progress_callback(msg_session_id)
                        registered_session_ids.discard(msg_session_id)

    except WebSocketDisconnect:
        is_connected = False
        _cleanup_progress_callbacks(chat_service, registered_session_ids)
        print("🔌 WebSocket 连接已断开")
    except Exception as e:
        is_connected = False
        _cleanup_progress_callbacks(chat_service, registered_session_ids)
        error_trace = traceback.format_exc()
        print(f"❌ WebSocket 顶层错误: {type(e).__name__}: {e}")
        print(f"详细错误堆栈:\n{error_trace}")

        # 尝试向客户端发送错误消息
        try:
            if not websocket.client_state.DISCONNECTED:
                await websocket.send_json({
                    "type": "error",
                    "content": f"连接错误: {str(e)}",
                    "timestamp": datetime.now().isoformat()
                })
        except:
            pass

        # 尝试关闭连接
        try:
            await websocket.close()
        except:
            pass
