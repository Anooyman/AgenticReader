"""
Session Manager for AgenticReader

管理所有聊天会话的持久化存储。
所有会话统一存储在 data/sessions/{session_id}.json
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


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
        """保存会话文件"""
        try:
            with open(session_path, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
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
        agents_used: Optional[List[str]] = None
    ):
        """
        保存消息到会话

        Args:
            session_id: 会话ID
            role: 消息角色 (user/assistant)
            content: 消息内容
            references: 引用信息（可选）
            agents_used: 本条消息使用的agent列表（可选）
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

    def get_session_history_for_llm(self, session: Dict) -> List[Dict[str, str]]:
        """将会话历史转换为 LLM 可用的格式"""
        history = []
        for msg in session.get("messages", []):
            history.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        return history

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
