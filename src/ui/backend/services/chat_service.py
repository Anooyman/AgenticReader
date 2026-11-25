"""聊天服务"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from src.agents.answer import AnswerAgent
from src.agents.orchestrator import ask as orchestrator_ask
from src.config.settings import resolve_provider
from .session_manager import SessionManager

# Orchestrator 的 sub-agent name -> 展示用 agent 标签，用于写入 session 的
# agents_used（沿用旧 UI 里 RetrievalAgent/SearchAgent 这类标签习惯）。
_SOURCE_TO_AGENT_LABEL = {
    "search_memory": "MemorySearch",
    "deep_dive_document": "DeepDive",
    # 第三个子 agent：网络搜索。工具名与 AnswerAgent 侧的 ANSWER_TOOLS 保持
    # 同名（search_web），标签按 UI 既有风格另起。
    "search_web": "WebSearch",
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

        # 按 session_id 注册的进度回调：值为 {token: callback} 而非单一
        # 回调。连接才是回调的拥有者，不是消息——同一会话开着两个连接
        # （双标签页很常见）时，键为 session 的旧"后到覆盖"写法会把先
        # 注册的连接顶掉；任一连接断线注销又会把另一条还活着的连接
        # 需要的整键抹掉。token 用 callback 的 id：同一回调对象重复
        # 注册幂等，不同连接各自的闭包互不相干。
        self._progress_callbacks: Dict[str, Dict[int, Any]] = {}

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
            #
            # provider 一律经 resolve_provider(None) 取——这里曾经是
            # `load_config().get("provider", "openai")`：load_config 的默认
            # 字典恒含 "provider": "openai" 这个键，于是显式值一路短路
            # resolve_provider 的"app_config → env PROVIDER → openai"链，
            # 只在 .env 里设了 PROVIDER 的环境会出现"文档索引用 azure、
            # 聊天用 openai"这种分裂，且没有任何日志能解释来源。
            provider = resolve_provider(None)
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
            # 长会话由 SessionManager 做窗口化 + 早期摘要，不再原样把整段
            # 历史灌给编排模型（详见 session_manager.history_for_llm_async）。
            history = await self.session_manager.history_for_llm_async(session)

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

            # 会话级记忆检索范围：缺省/None 交给 orchestrator 子 agent 的
            # 补值链，最终由 src/memory/gateway 换成自库白名单（D-B 缺省）。
            memory_namespaces = session.get("memory_namespaces") or None

            result = await orchestrator_ask(
                user_query,
                doc_name=doc_name,
                namespaces=memory_namespaces,
                history=history,
                on_progress=on_progress,
                # provider 留空让 ask() 自己走 resolve_provider(None)——与
                # 上面文档校验路径同一个解析入口，一次提问里编排 LLM 和全部
                # 子 agent 用的都是它。（此前这里传 load_config().get(...)，
                # 等于把 env PROVIDER 这一级从聊天主线上抹掉了。）
                #
                # enabled_tools 现在是真的进工具集了，不再是纯展示元数据：
                # 前端的「🌐 网络搜索」开关会决定 search_web 要不要广告给
                # 编排模型，见 orchestrator/agent.py 的 _advertised_tools。
                enabled_tools=list(current_tools or []),
            )

            final_answer = result.get("answer", "")
            sources_used = result.get("sources_used", [])
            # 本轮检索命中——跟着消息存下来，前端在回复下方渲染
            # "提及论文"可下载条目（点不点由用户挑，系统零自动动作）。
            memory_hits = result.get("memory_hits") or []

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
                agents_used=agents_used,
                memory_hits=memory_hits or None
            )

            # 更新会话级别的agents统计
            self.session_manager.update_session_agents(session_id, agents_used)

            # 更新 current_session
            self.current_session = self.session_manager.load_session(session_id)

            return {
                "answer": final_answer,
                "references": references,
                "memory_hits": memory_hits,
                "enabled_tools": current_tools,
                "selected_docs": current_docs
            }

        except Exception as e:
            print(f"❌ 聊天处理失败: {e}")
            import traceback
            traceback.print_exc()
            return {"answer": f"处理失败: {str(e)}", "references": [], "memory_hits": []}

    def register_progress_callback(self, session_id: Optional[str], callback):
        """按会话注册进度回调，返回可摘除的 token（id(callback)）。

        同一回调对象重复注册幂等——websocket 每条消息都可能再递一遍
        同一个闭包，若每次都是新条目，进度事件会被重复 fan-out 到同一
        条连接。"""
        if not session_id or callback is None:
            return None
        token = id(callback)
        self._progress_callbacks.setdefault(str(session_id), {})[token] = callback
        return token

    def unregister_progress_callback(self, session_id: Optional[str], token=None) -> None:
        """注销进度回调。带 token：只摘这条连接自己的那份；不带：整键
        清空——那是 delete_session 这类"会话没了"的批量清理用的旧语义。"""
        if not session_id:
            return
        key = str(session_id)
        if token is None:
            self._progress_callbacks.pop(key, None)
            return
        entries = self._progress_callbacks.get(key)
        if entries:
            entries.pop(token, None)
            if not entries:
                self._progress_callbacks.pop(key, None)

    def _resolve_progress_callback(self, session_id: Optional[str]):
        """取该会话的进度回调；多条连接并存时返回 fan-out 广播，
        查不到时回退到全局 progress_callback。"""
        callbacks = []
        if session_id:
            entries = self._progress_callbacks.get(str(session_id))
            callbacks = list(entries.values()) if entries else []
        if not callbacks:
            return self.progress_callback
        if len(callbacks) == 1:
            return callbacks[0]

        async def _fan_out(data):
            # 一条连接的发送失败不许废掉其它连接；也不该把异常再抛回
            # 事件源头——chat() 只是在"通知有人看进度"，不是事务的一部分。
            for cb in callbacks:
                try:
                    res = cb(data)
                    if res is not None:
                        await res
                except Exception:  # noqa: BLE001
                    pass
            return None

        return _fan_out

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
        """删除指定会话，并把它在记忆侧留下的痕迹一起回收

        顺序是有讲究的，两步都不许反：
        1. 先让 SessionManager 删文件——文件不存在它抛 FileNotFoundError
           （API 层据此回 404），此时后面两步一概不做，免得对着一个根本
           没删掉的会话做"回收"。
        2. 再清 memory 行：这条会话经 chat_ingest 车道写进 webapp-chat 的
           那批 chunk，source_id 就是 session_id，不删的话用户删了会话
           却还在 /chat 里被"我记得上次我们聊过…"召回——这是最要命的
           隐私泄漏面，比占地方严重得多。
        3. 最后清 chat_ingest 的水位线条目，否则那个键会永久留在
           chat_ingest_state.json 里（扫描只认现存的 session 文件）。

        记忆回收失败不能把删除动作拖失败：会话文件已经没了，回滚没有意义，
        所以两步都是尽力而为 + 打日志——把异常抛回调用方只会让人以为"会话
        没删掉"而多点一次删除。
        """
        self.session_manager.delete_session(session_id)

        memory_deleted = 0
        try:
            from src.memory import gateway  # 函数级：service 层不往模块级拖记忆内核
            memory_deleted = gateway.delete_source(gateway.NAMESPACE_WEBAPP_CHAT, session_id)
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  会话 {session_id} 的记忆行清理失败（会话已删除，记忆需手动清）: {e}")
        try:
            from .chat_ingest import forget_session
            forget_session(session_id)
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  会话 {session_id} 的入库水位线条目清理失败: {e}")
        if memory_deleted:
            print(f"🧹 已回收会话 {session_id} 的 webapp-chat 记忆行 {memory_deleted} 条")

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
