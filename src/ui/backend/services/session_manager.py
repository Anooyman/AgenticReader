"""
Session Manager for AgenticReader

管理所有聊天会话的持久化存储。
所有会话统一存储在 data/sessions/{session_id}.json
"""

from collections import OrderedDict
import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

from src.config.settings import resolve_provider
from src.utils.json_io import write_json_atomic

logger = logging.getLogger(__name__)


# ---- 会话历史窗口化 / 早期摘要 ----
# 原文保留的最近消息条数。取值依据：对话"正文"一般就落在最近几轮到十几轮，
# 20 条 ≈ 10 轮问答，够模型拿住指代与刚讨论过的细节，又不至于长会话每轮
# 都把整段历史重发一遍（旧实现的真实行为）。
HISTORY_WINDOW_MESSAGES = 20

# 摘要合并结果的上限。超过它就对全量更早消息重算一次，避免这条摘要块
# 随会话无限膨胀——那正好违背做窗口化的初衷。
HISTORY_SUMMARY_MAX_CHARS = 4000

# 摘要缓存（session_id -> {"covered": 已覆盖条数, "text": 摘要}）。
# 只放在进程里，理由见 history_for_llm_async 的 docstring。
_HISTORY_SUMMARIES: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_HISTORY_SUMMARIES_MAX = 64


def _remember_history_summary(session_id: str, covered: int, text: str) -> None:
    """写入摘要缓存（有界：超出淘汰最久未用到的会话）。"""
    if not session_id or not text:
        return
    _HISTORY_SUMMARIES[session_id] = {"covered": covered, "text": text}
    _HISTORY_SUMMARIES.move_to_end(session_id)
    while len(_HISTORY_SUMMARIES) > _HISTORY_SUMMARIES_MAX:
        _HISTORY_SUMMARIES.popitem(last=False)


def _summarize_new_prefix(dropped: List[Dict], covered: int, provider: str,
                          previous: str) -> str:
    """把"掉出窗口但还没被摘要覆盖"的那一段消息并进已有摘要，返回新的全文。

    同步函数，调用方要放去线程里跑（history_for_llm_async 用的
    asyncio.to_thread）。摘要机制本身不自造一套：直接借
    src/core/llm/history.py 里现成的 LimitedChatMessageHistory——它已经把
    "消息列表 → 喂给 LLM 的对话文本" 和 "调 LLM 拿摘要并容错" 都写好了
    （_format_messages_for_summary / _call_llm_for_summary），本项目别的
    agent 也走同一个类，行为口径一致。

    为什么不用它现成的"自动压缩"入口（add_message 里那条）：
    history.py 的压缩策略是把**全部**消息总结成 1 条然后清空原文
    （docstring 自己写的"不保留原始对话"）——用它会把我要留的最近 20 条
    原文一起吃掉。所以这里只借它的两块能力，窗口策略自己拿。

    covered 之前的消息已经在 previous 摘要里，本次只算新增的那一段
    （通常几条），所以正常情况下这趟 LLM 调用很短。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    from src.core.llm import LLMBase
    from src.core.llm.history import LimitedChatMessageHistory

    fresh = dropped[covered:]
    if not fresh:
        return previous

    lc_messages = [
        HumanMessage(content=m.get("content") or "")
        if (m.get("role") or "assistant") == "user" else AIMessage(content=m.get("content") or "")
        for m in fresh
    ]
    try:
        hist = LimitedChatMessageHistory(use_llm_summary=True,
                                         llm_client=LLMBase(provider=provider))
        conversation = hist._format_messages_for_summary(lc_messages)
        if not conversation.strip():
            return previous
        prompt = (
            "请把下面的对话片段总结成简洁要点，保留：讨论过什么、给出了什么结论、"
            "用户表达过的偏好或约束、以及后续对话可能要用到的背景事实。\n\n"
            f"{conversation}\n\n"
            "只输出总结本身，不要复述原文。\n总结："
        )
        addition = (hist._call_llm_for_summary(prompt) or "").strip()
    except Exception:  # noqa: BLE001 —— 摘要路径的失败不该冒泡到一次正常提问
        logger.warning("会话历史摘要失败（provider=%s），按截断处理", provider, exc_info=True)
        return previous

    if not addition:
        return previous

    merged = f"{previous}\n\n{addition}".strip() if previous else addition
    if len(merged) <= HISTORY_SUMMARY_MAX_CHARS:
        return merged

    # 合并后太长：对全部更早消息重算一次，把摘要本身压回预算内。
    try:
        hist = LimitedChatMessageHistory(use_llm_summary=True,
                                         llm_client=LLMBase(provider=provider))
        whole = hist._format_messages_for_summary([
            HumanMessage(content=m.get("content") or "")
            if (m.get("role") or "assistant") == "user" else AIMessage(content=m.get("content") or "")
            for m in dropped
        ])
        return (hist._call_llm_for_summary(
            "请把下面这段很长的对话史压成一段简短摘要（不超过 600 字），"
            "保留话题、结论与用户偏好：\n\n" + whole + "\n\n总结：") or "").strip() or merged
    except Exception:  # noqa: BLE001
        return merged


class SessionManager:
    """会话管理器"""

    def __init__(self, base_dir: str = "data/sessions"):
        self.base_dir = Path(base_dir)
        # 缓存: {session_id: session_id}
        self._session_cache = {}
        # doc_name -> session_id 快速查找（用于单文档模式自动加载）
        self._doc_session_map = {}

        self._ensure_directories()
        self._migrate_old_directories()
        self._build_cache()

    def _ensure_directories(self):
        """确保会话目录存在"""
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _migrate_old_directories(self):
        """一次性迁移旧 mode 子目录到平级目录"""
        migrated = 0
        for mode in ["single", "cross", "manual"]:
            old_dir = self.base_dir / mode
            if not old_dir.exists():
                continue
            for old_file in old_dir.glob("*.json"):
                try:
                    data = self._load_session_file(old_file)
                    if data and data.get("session_id"):
                        new_path = self.base_dir / f"{data['session_id']}.json"
                        if not new_path.exists():
                            self._save_session_file(new_path, data)
                            migrated += 1
                        old_file.unlink()
                except Exception as e:
                    logger.warning(f"迁移文件失败 {old_file}: {e}")
                    continue
            # 尝试删除空目录
            try:
                if old_dir.exists() and not any(old_dir.iterdir()):
                    old_dir.rmdir()
            except Exception:
                pass

        if migrated > 0:
            logger.info(f"✅ 已迁移 {migrated} 个旧会话文件到平级目录")

    def _build_cache(self):
        """构建会话缓存（启动时执行一次）"""
        logger.info("🔧 构建会话缓存...")
        cache_count = 0

        for file_path in self.base_dir.glob("*.json"):
            if file_path.name == "metadata.json":
                continue
            try:
                session_data = self._load_session_file(file_path)
                if session_data:
                    session_id = session_data.get("session_id")
                    if session_id:
                        self._session_cache[session_id] = session_id
                        # 建立 doc_name -> session_id 映射
                        doc_name = session_data.get("doc_name")
                        mode = session_data.get("mode")
                        if mode == "single" and doc_name:
                            self._doc_session_map[doc_name] = session_id
                        cache_count += 1
            except Exception as e:
                logger.warning(f"缓存构建失败 {file_path}: {e}")
                continue

        logger.info(f"✅ 会话缓存构建完成，共 {cache_count} 个会话")

    def _get_session_path(self, session_id: str) -> Path:
        """获取会话文件路径"""
        return self.base_dir / f"{session_id}.json"

    def _load_session_file(self, session_path: Path) -> Optional[Dict]:
        """加载会话文件"""
        if not session_path.exists():
            return None
        try:
            with open(session_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载会话文件失败 {session_path}: {e}")
            return None

    def _save_session_file(self, session_path: Path, session_data: Dict):
        """保存会话文件（原子落盘：tmp + os.replace）。

        写侧走 write_json_atomic 与本仓库状态文件范式一致（registry/queue_store）：
        WS 车道与 chat_ingest 车道会同读同一 session JSON，进程中途被杀不能留
        半截文件。读侧 _load_session_file 保持容错（坏文件返回 None 不炸启动）。

        本方法是同步函数、跑在事件循环线程里——同步块内部不会被其它协程打断，
        因此单进程内的读-改-写交错已被事件循环串行化；跨进程防护留给
        write_json_atomic 的原子替换语义。"""
        try:
            write_json_atomic(session_path, session_data)
        except Exception as e:
            logger.error(f"保存会话文件失败 {session_path}: {e}")
            raise

    def create_or_load_single_session(self, doc_name: str) -> Dict:
        """
        为单文档模式创建或加载会话

        Args:
            doc_name: 文档名称

        Returns:
            会话数据
        """
        # 先从缓存查找
        if doc_name in self._doc_session_map:
            session_id = self._doc_session_map[doc_name]
            session_path = self._get_session_path(session_id)
            existing = self._load_session_file(session_path)
            if existing:
                logger.info(f"加载现有单文档会话: {doc_name}")
                return existing

        # 缓存未命中，遍历查找
        for file_path in self.base_dir.glob("*.json"):
            if file_path.name == "metadata.json":
                continue
            try:
                data = self._load_session_file(file_path)
                if data and data.get("mode") == "single" and data.get("doc_name") == doc_name:
                    # 更新缓存
                    sid = data["session_id"]
                    self._session_cache[sid] = sid
                    self._doc_session_map[doc_name] = sid
                    logger.info(f"加载现有单文档会话: {doc_name}")
                    return data
            except Exception:
                continue

        # 创建新会话
        logger.info(f"创建新单文档会话: {doc_name}")
        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "mode": "single",
            "doc_name": doc_name,
            "selected_docs": [doc_name],
            "enabled_tools": ["retrieve_documents"],
            "agents_used": [],  # 初始化agents记录
            # 会话级记忆检索范围；None/缺字段 = 缺省自库白名单（gateway 解析）
            "memory_namespaces": None,
            "title": f"单文档对话: {doc_name}",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "message_count": 0,
            "messages": []
        }

        self._save_session_file(self._get_session_path(session_id), session_data)
        self._session_cache[session_id] = session_id
        self._doc_session_map[doc_name] = session_id

        return session_data

    def create_session(
        self,
        mode: str = "cross",
        doc_name: Optional[str] = None,
        selected_docs: Optional[List[str]] = None,
        enabled_tools: Optional[List[str]] = None,
        title: Optional[str] = None
    ) -> Dict:
        """
        创建新会话

        Args:
            mode: 会话类型标签 (single/cross/manual)，仅用于元数据
            doc_name: 文档名称（单文档模式）
            selected_docs: 选中的文档列表
            enabled_tools: 启用的工具列表
            title: 会话标题（可选，自动生成）
        """
        if mode == "single" and doc_name:
            return self.create_or_load_single_session(doc_name)

        session_id = str(uuid.uuid4())

        if not title:
            if mode == "cross":
                title = f"跨文档对话 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            elif mode == "manual":
                doc_count = len(selected_docs) if selected_docs else 0
                title = f"手动选择模式 ({doc_count}个文档) - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            else:
                title = f"对话 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        session_data = {
            "session_id": session_id,
            "mode": mode,
            "doc_name": doc_name,
            "selected_docs": selected_docs,
            "enabled_tools": enabled_tools or [],
            "agents_used": [],  # 初始化agents记录
            # 会话级记忆检索范围；None/缺字段 = 缺省自库白名单（gateway 解析）
            "memory_namespaces": None,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "message_count": 0,
            "messages": []
        }

        self._save_session_file(self._get_session_path(session_id), session_data)
        self._session_cache[session_id] = session_id

        logger.info(f"创建新会话: {mode} - {session_id}")
        return session_data

    def load_session(self, session_id: str) -> Optional[Dict]:
        """
        加载指定会话

        Args:
            session_id: 会话ID
        """
        session_path = self._get_session_path(session_id)
        session_data = self._load_session_file(session_path)
        if session_data:
            self._session_cache[session_id] = session_id
            return session_data

        logger.warning(f"会话不存在: {session_id}")
        return None

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        references: Optional[List] = None,
        agents_used: Optional[List[str]] = None,
        memory_hits: Optional[List] = None
    ):
        """
        保存消息到会话

        Args:
            session_id: 会话ID
            role: 消息角色 (user/assistant)
            content: 消息内容
            references: 引用信息（可选）
            agents_used: 本条消息使用的agent列表（可选）
            memory_hits: 本轮检索命中的记忆条目（可选，供 UI 渲染
                "提及论文可下载"条目——没有它，历史消息刷新后按钮会丢）
        """
        session_path = self._get_session_path(session_id)
        session_data = self._load_session_file(session_path)

        if not session_data:
            logger.error(f"会话不存在，无法保存消息: {session_id}")
            return

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        if references:
            message["references"] = references

        if memory_hits:
            message["memory_hits"] = memory_hits

        if agents_used:
            message["agents_used"] = agents_used

        session_data["messages"].append(message)
        session_data["message_count"] = len(session_data["messages"])
        session_data["updated_at"] = datetime.now().isoformat()

        self._save_session_file(session_path, session_data)
        logger.debug(f"保存消息到会话: {session_id} - {role}")

    def update_session_agents(self, session_id: str, agents_used: List[str]):
        """
        更新会话级别的agents统计

        Args:
            session_id: 会话ID
            agents_used: 本次使用的agent列表
        """
        if not agents_used:
            return

        session_path = self._get_session_path(session_id)
        session_data = self._load_session_file(session_path)

        if not session_data:
            logger.error(f"会话不存在，无法更新agents: {session_id}")
            return

        # 初始化或更新 agents_used 集合
        if "agents_used" not in session_data:
            session_data["agents_used"] = []

        # 合并新使用的agents（去重）
        for agent in agents_used:
            if agent not in session_data["agents_used"]:
                session_data["agents_used"].append(agent)

        self._save_session_file(session_path, session_data)
        logger.debug(f"更新会话agents: {session_id} - {session_data['agents_used']}")

    async def history_for_llm_async(self, session: Dict,
                                    provider: Optional[str] = None) -> List[Dict[str, str]]:
        """会话历史 → LLM 可用的历史（窗口化 + 早期摘要）。

        为什么要改这里：原来的 get_session_history_for_llm 把
        session["messages"] 原样搬出去，一条不裁。会话是永久落盘的、只有
        /chat 清空按钮才会清，于是长会话每一轮都把自己整段历史重发一遍——
        成本随轮次线性涨，而且第一轮的请求就已经把模型窗口占满
        （Orchestrator 那道 MAX_CONTEXT_CHARS 以前只在看完成本之后才做）。
        现在切成两段：

          * 最近 HISTORY_WINDOW_MESSAGES 条：原文照给。这是"我们在聊什么"
            的正文，摘要化反而会丢指代与细节，得留原文。
          * 更早的部分：压成开头一条 system 摘要块，块里明说更早的 N 条
            原文已省略——模型知道自己在看摘要，才不会把摘要里的说法当成
            "用户原话"来引用。

        摘要不是每轮重算：结果按 session_id 记进进程内的 _HISTORY_SUMMARIES
        缓存，且按"只补摘要新掉出窗口的那一段"增量合并，所以一条超长会话
        摊到每轮大约只多一次很短的 LLM 调用。缓存不落盘这点是刻意的——
        把摘要写回 session JSON 就得在历史读路径上做读-改-写，而
        save_message 也在写同一个文件，为了省一次 LLM 调用去引入丢消息的
        风险不值当；代价是进程重启后的第一问会付一次全量摘要。

        LLM 不可用 / 摘要失败时退化为纯截断（只给窗口内原文 + 一句"早期
        历史已省略"），绝不因为这条辅助路径失败就让一次正常提问报错。
        """
        messages = session.get("messages") or []
        if len(messages) <= HISTORY_WINDOW_MESSAGES:
            return [self._as_history_entry(m) for m in messages]

        kept = [self._as_history_entry(m) for m in messages[-HISTORY_WINDOW_MESSAGES:]]
        dropped = messages[:-HISTORY_WINDOW_MESSAGES]
        session_id = session.get("session_id") or ""
        resolved = resolve_provider(provider)

        entry = _HISTORY_SUMMARIES.get(session_id) if session_id else None
        if entry and entry["covered"] >= len(dropped):
            summary = entry["text"]
        else:
            covered = entry["covered"] if entry else 0
            summary = await asyncio.to_thread(
                _summarize_new_prefix, dropped, covered, resolved,
                entry["text"] if entry else "")
            if summary:
                _remember_history_summary(session_id, len(dropped), summary)

        if summary:
            note = (
                f"[早期对话摘要] 本会话更早的 {len(dropped)} 条消息未以原文注入，"
                f"以下是它们的要点：\n\n{summary}"
            )
        else:
            # 摘要失败也要交代"少了东西"，别让模型以为眼前就是完整对话史。
            note = (f"[早期历史已省略] 本会话更早的 {len(dropped)} 条消息因摘要不可用"
                    f"未注入上下文。")
        return [{"role": "system", "content": note}] + kept

    @staticmethod
    def _as_history_entry(msg: Dict) -> Dict[str, str]:
        return {"role": msg.get("role") or "assistant", "content": msg.get("content") or ""}

    def get_messages_range(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        获取指定范围的历史消息（用于分页加载）

        Args:
            session_id: 会话ID
            offset: 偏移量（从后往前数）
            limit: 返回的消息数量
        """
        session = self.load_session(session_id)
        if not session:
            return {"messages": [], "total": 0, "has_more": False}

        all_messages = session.get("messages", [])
        total = len(all_messages)

        start_idx = max(0, total - offset - limit)
        end_idx = total - offset

        messages = all_messages[start_idx:end_idx]
        has_more = start_idx > 0

        return {
            "messages": messages,
            "total": total,
            "has_more": has_more
        }

    def list_sessions(self, limit: Optional[int] = None) -> List[Dict]:
        """
        列出所有会话

        Args:
            limit: 限制返回数量（可选）

        Returns:
            会话列表（按更新时间倒序）
        """
        sessions = []

        for session_file in self.base_dir.glob("*.json"):
            if session_file.name == "metadata.json":
                continue
            session_data = self._load_session_file(session_file)
            if session_data:
                summary = {
                    "session_id": session_data.get("session_id"),
                    "mode": session_data.get("mode"),
                    "doc_name": session_data.get("doc_name"),
                    "selected_docs": session_data.get("selected_docs"),
                    "enabled_tools": session_data.get("enabled_tools"),
                    "memory_namespaces": session_data.get("memory_namespaces"),
                    "title": session_data.get("title"),
                    "created_at": session_data.get("created_at"),
                    "updated_at": session_data.get("updated_at"),
                    "message_count": session_data.get("message_count", 0)
                }
                sessions.append(summary)

        sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

        if limit:
            sessions = sessions[:limit]

        return sessions

    def delete_session(self, session_id: str):
        """
        删除指定会话

        Args:
            session_id: 会话ID
        """
        session_path = self._get_session_path(session_id)

        if not session_path.exists():
            error_msg = f"会话文件不存在: {session_id}"
            logger.error(f"❌ {error_msg}")
            raise FileNotFoundError(error_msg)

        try:
            # 先读取以更新 doc_session_map
            data = self._load_session_file(session_path)
            if data and data.get("mode") == "single" and data.get("doc_name"):
                self._doc_session_map.pop(data["doc_name"], None)

            session_path.unlink()
            self._session_cache.pop(session_id, None)
            logger.info(f"✅ 删除会话: {session_id}")
        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"❌ 删除会话失败: {e}")
            raise

    def rename_session(self, session_id: str, new_title: str) -> Optional[Dict]:
        """
        重命名会话

        Args:
            session_id: 会话ID
            new_title: 新标题

        Returns:
            更新后的会话数据
        """
        session = self.load_session(session_id)
        if not session:
            return None

        session["title"] = new_title
        session["updated_at"] = datetime.now().isoformat()

        session_path = self._get_session_path(session_id)
        self._save_session_file(session_path, session)

        return session

    def set_session_memory_namespaces(self, session_id: str,
                                     namespaces: Optional[List[str]]) -> Optional[Dict]:
        """
        设置会话级记忆检索范围。

        Args:
            session_id: 会话ID
            namespaces: namespace 列表；None 表示恢复默认（自库白名单，
                由 src/memory/gateway 解析）。值的合法性校验属调用方
                （api 层）的职责，本方法只做落盘。

        Returns:
            更新后的会话数据；会话不存在时返回 None。
        """
        session = self.load_session(session_id)
        if not session:
            return None

        session["memory_namespaces"] = namespaces
        session["updated_at"] = datetime.now().isoformat()

        session_path = self._get_session_path(session_id)
        self._save_session_file(session_path, session)

        return session
