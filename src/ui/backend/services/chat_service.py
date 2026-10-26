"""聊天服务"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from src.agents.answer import AnswerAgent
from src.agents.orchestrator import ask as orchestrator_ask
from .session_manager import SessionManager
from ..api.v1.config import load_config

# Orchestrator 的 sub-agent name -> 展示用 agent 标签，用于写入 session 的
# agents_used（沿用旧 UI 里 RetrievalAgent/SearchAgent 这类标签习惯）。
_SOURCE_TO_AGENT_LABEL = {
    "search_memory": "MemorySearch",
    "deep_dive_document": "DeepDive",
}


class ChatService:
    """聊天服务单例"""

    def __init__(self):
        self.enabled_tools: List[str] = []
        self.selected_docs: Optional[list] = None
        self.session_manager = SessionManager()
        # 最近一次活跃会话，仅用于 /sessions/current 之类的默认展示；
        # 真正的持久化写入一律按显式 session_id 定位（见 chat/reset）。
        self.current_session: Optional[Dict] = None
        self.progress_callback = None

        # 按 session_id 注册的进度回调：多会话共享本单例时，避免回调被后到
        # 的连接/请求覆写（websocket 侧注册/注销，chat 调用时查表取用）。
        self._progress_callbacks: Dict[str, Any] = {}

        # 仅用于校验手动选择的文档是否存在（AnswerAgent 实例缓存池，避免
        # 重复创建）；真正的问答走 Orchestrator，见 chat()。
        self._agent_cache: Dict[str, AnswerAgent] = {}  # {provider: AnswerAgent}

    def initialize(
        self,
        enabled_tools: Optional[List[str]] = None,
        selected_docs: Optional[list] = None,
        session_id: Optional[str] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        初始化聊天服务

        Args:
            enabled_tools: 用户启用的工具列表 ["retrieve_documents", "search_web"]
            selected_docs: 用户选择的文档列表
            session_id: 会话ID（可选，用于加载历史会话）
            progress_callback: 进度回调函数（可选）
        """
        try:
            self.enabled_tools = enabled_tools or []
            self.selected_docs = selected_docs
            # 兼容旧调用方：self.progress_callback 仍保留为默认回调，但更优
            # 先级是按 session_id 注册的字典回调（见 _resolve_progress_callback）。
            self.progress_callback = progress_callback

            print(f"🔧 初始化聊天服务: enabled_tools={self.enabled_tools}, selected_docs={self.selected_docs}, session_id={session_id}")

            # 会话管理
            if session_id:
                self.current_session = self.session_manager.load_session(session_id)
                if not self.current_session:
                    return {"success": False, "error": "会话不存在"}

                # 从会话恢复工具/文档选择
                self.selected_docs = self.current_session.get("selected_docs")
                self.enabled_tools = self.current_session.get("enabled_tools", self.enabled_tools)

                # 兼容旧 session：单文档模式下 selected_docs 可能为 null
                if not self.selected_docs and self.current_session.get("doc_name"):
                    self.selected_docs = [self.current_session["doc_name"]]
                if not self.enabled_tools and self.current_session.get("doc_name"):
                    self.enabled_tools = ["retrieve_documents"]

                print(f"✅ 加载历史会话: {session_id}")
            else:
                # 推断 mode（仅用于元数据/标题生成）
                if self.selected_docs and len(self.selected_docs) == 1:
                    inferred_mode = "single"
                    doc_name = self.selected_docs[0]
                elif self.selected_docs and len(self.selected_docs) > 1:
                    inferred_mode = "manual"
                    doc_name = None
                else:
                    inferred_mode = "cross"
                    doc_name = None

                if inferred_mode == "single" and doc_name:
                    self.current_session = self.session_manager.create_or_load_single_session(doc_name)
                else:
                    self.current_session = self.session_manager.create_session(
                        mode=inferred_mode,
                        doc_name=doc_name,
                        selected_docs=self.selected_docs,
                        enabled_tools=self.enabled_tools
                    )

                # 保存 enabled_tools / selected_docs 到 session
                self.current_session["enabled_tools"] = self.enabled_tools
                self.current_session["selected_docs"] = self.selected_docs
                print(f"✅ 创建/加载会话: {self.current_session['session_id']}")

            # 进度回调按会话ID注册（而不是只存全局字段），这样后续 chat/进度
            # 输出一定落在本会话上，不会被另一个连接的 initialize 覆盖。
            if progress_callback and self.current_session:
                self.register_progress_callback(
                    self.current_session.get("session_id"), progress_callback
                )

            # AnswerAgent 现在只用于校验用户手动选择的文档是否存在
            # （真正的问答走 Orchestrator，deep_dive_document 子 agent 内部
            # 会自己按需实例化 AnswerAgent，这里不再需要长期持有一个带
            # 历史状态的实例）。
            config = load_config()
            provider = config.get("provider", "openai")
            print(f"📌 使用 LLM Provider: {provider}")

            if self.selected_docs and "retrieve_documents" in self.enabled_tools:
                # _agent_cache 以 provider 为 key 本身就是"换配置即失效"：
                # /config 页切 provider 后下一个请求直接 cache-miss 建新实例，
                # 不需要额外的 _current_provider 标量。
                if provider not in self._agent_cache:
                    self._agent_cache[provider] = AnswerAgent(provider=provider)
                validator_agent = self._agent_cache[provider]

                valid_docs, invalid_docs = validator_agent.validate_manual_selected_docs(self.selected_docs)
                if invalid_docs:
                    print(f"⚠️  以下文档未找到: {invalid_docs}")
                if valid_docs:
                    self.selected_docs = valid_docs
                else:
                    self.selected_docs = None
                    print("⚠️  所有文档无效，将使用自动文档选择")

            print(f"✅ 聊天服务初始化成功")

            # 返回会话信息
            all_messages = self.current_session.get("messages", [])
            total_message_count = len(all_messages)
            initial_message_limit = 20
            recent_messages = all_messages[-initial_message_limit:] if total_message_count > initial_message_limit else all_messages

            return {
                "success": True,
                "session_id": self.current_session["session_id"],
                "enabled_tools": self.enabled_tools,
                "selected_docs": self.selected_docs,
                "title": self.current_session.get("title", "新对话"),
                "message_count": total_message_count,
                "messages": recent_messages,
                "has_more_messages": total_message_count > initial_message_limit
            }

        except Exception as e:
            print(f"❌ 聊天服务初始化失败: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def chat(
        self,
        user_query: str,
        progress_callback=None,
        enabled_tools: Optional[List[str]] = None,
        selected_docs: Optional[list] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """处理聊天消息——统一走 Orchestrator（是否检索 memory/深挖原文由
        LLM 自行判断，见 src/agents/orchestrator）。

        Args:
            session_id: 目标会话ID。显式传入时所有持久化写入都按该 id 定位，
                不再依赖 self.current_session；缺省时回退到最近活跃会话，
                以兼容旧客户端。
        """
        try:
            # 解析目标会话：显式 session_id 优先，缺省回退最近活跃会话
            session_id = session_id or (
                self.current_session.get("session_id") if self.current_session else None
            )
            if not session_id:
                return {"answer": "会话未初始化，请先初始化。", "references": []}

            session = self.session_manager.load_session(session_id)
            if not session:
                return {"answer": f"会话不存在或已被删除: {session_id}", "references": []}

            # 兼容旧调用方：显式回调注册到该会话名下，供后续进度查表使用
            if progress_callback:
                self.register_progress_callback(session_id, progress_callback)
                self.progress_callback = progress_callback

            # 使用本次消息的工具/文档设置（如果提供），否则用初始化时的
            current_tools = enabled_tools if enabled_tools is not None else self.enabled_tools
            current_docs = selected_docs if selected_docs is not None else self.selected_docs

            if enabled_tools is not None:
                self.enabled_tools = enabled_tools
            if selected_docs is not None:
                self.selected_docs = selected_docs

            # 单文档模式下把 doc_name 告知 Orchestrator，让它可以调用
            # deep_dive_document；跨文档/纯对话模式下留空，只能靠 search_memory。
            doc_name = current_docs[0] if current_docs and len(current_docs) == 1 else None

            # Orchestrator 自己管理对话历史，这里从会话文件里取（在保存本次
            # 用户消息之前读取，避免在 messages 里重复出现这条消息）。
            history = self.session_manager.get_session_history_for_llm(session)

            # 保存用户消息
            self.session_manager.save_message(
                session_id=session_id,
                role="user",
                content=user_query
            )

            async def on_progress(stage: str, detail: str):
                cb = self._resolve_progress_callback(session_id)
                if not cb:
                    return
                data = {"agent": "orchestrator", "stage": stage, "message": detail}
                cb_result = cb(data)
                if cb_result is not None:
                    await cb_result

            result = await orchestrator_ask(
                user_query,
                doc_name=doc_name,
                history=history,
                on_progress=on_progress,
                # 与文档校验路径同源：/config 页选的 provider 真正贯通到
                # 编排 LLM 与全部子 agent（此前 orchestrator 内部写死 openai）。
                provider=load_config().get("provider"),
            )

            final_answer = result.get("answer", "")
            sources_used = result.get("sources_used", [])

            # agents_used：把 Orchestrator 的子 agent name 映射成展示标签
            agents_used = []
            for name in sources_used:
                label = _SOURCE_TO_AGENT_LABEL.get(name, name)
                if label not in agents_used:
                    agents_used.append(label)

            references: List[Dict[str, Any]] = []
            if doc_name:
                references.append({"doc_name": doc_name, "similarity_score": None})

            # 保存助手回复（包含agents_used）
            self.session_manager.save_message(
                session_id=session_id,
                role="assistant",
                content=final_answer,
                references=references,
                agents_used=agents_used
            )

            # 更新会话级别的agents统计
            self.session_manager.update_session_agents(session_id, agents_used)

            # 更新 current_session
            self.current_session = self.session_manager.load_session(session_id)

            return {
                "answer": final_answer,
                "references": references,
                "enabled_tools": current_tools,
                "selected_docs": current_docs
            }

        except Exception as e:
            print(f"❌ 聊天处理失败: {e}")
            import traceback
            traceback.print_exc()
            return {"answer": f"处理失败: {str(e)}", "references": []}

    def register_progress_callback(self, session_id: Optional[str], callback) -> None:
        """按会话ID注册进度回调（websocket 连接建立/收到带会话ID的消息时调用）"""
        if not session_id or callback is None:
            return
        self._progress_callbacks[str(session_id)] = callback

    def unregister_progress_callback(self, session_id: Optional[str]) -> None:
        """注销某个会话的进度回调（websocket 断开时调用）"""
        if session_id:
            self._progress_callbacks.pop(str(session_id), None)

    def _resolve_progress_callback(self, session_id: Optional[str]):
        """取该会话的进度回调；查不到时回退到全局 progress_callback"""
        cb = None
        if session_id:
            cb = self._progress_callbacks.get(str(session_id))
        return cb or self.progress_callback

    def reset(self, session_id: Optional[str] = None):
        """重置指定会话的消息历史

        Args:
            session_id: 要清空的历史会话ID；缺省时作用于最近活跃会话。
        """
        if not session_id:
            session_id = self.current_session.get("session_id") if self.current_session else None
        if not session_id:
            print("⚠️ 没有活跃的会话，无需重置")
            return

        # 清空 session 文件中的消息
        session = self.session_manager.load_session(session_id)
        if session:
            session["messages"] = []
            session["message_count"] = 0
            session["updated_at"] = datetime.now().isoformat()

            session_path = self.session_manager._get_session_path(session_id)
            self.session_manager._save_session_file(session_path, session)

            # 仅当重置的是最近活跃会话时才同步 current_session
            if self.current_session and self.current_session.get("session_id") == session_id:
                self.current_session = session
        elif self.current_session and self.current_session.get("session_id") == session_id:
            self.current_session["messages"] = []
            self.current_session["message_count"] = 0
            self.current_session["updated_at"] = datetime.now().isoformat()

        print(f"✅ 聊天服务已重置（session_id={session_id}）")

    def list_sessions(self, limit: Optional[int] = None) -> list:
        """列出会话列表"""
        return self.session_manager.list_sessions(limit)

    def delete_session(self, session_id: str):
        """删除指定会话"""
        self.session_manager.delete_session(session_id)
        # 该会话已不存在，顺带清掉它的进度回调，避免残留引用
        self.unregister_progress_callback(session_id)
        if self.current_session and self.current_session["session_id"] == session_id:
            self.current_session = None
            self.enabled_tools = []
            self.selected_docs = None

    def load_more_messages(self, offset: int = 0, limit: int = 20,
                           session_id: Optional[str] = None) -> Dict[str, Any]:
        """加载更多历史消息（session_id 缺省时取最近活跃会话）"""
        if not session_id:
            session_id = self.current_session.get("session_id") if self.current_session else None
        if not session_id:
            return {"messages": [], "total": 0, "has_more": False}

        return self.session_manager.get_messages_range(
            session_id=session_id,
            offset=offset,
            limit=limit
        )


# 全局单例
chat_service = ChatService()
