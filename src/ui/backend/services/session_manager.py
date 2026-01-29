"""
Session Manager for AgenticReader

管理所有聊天会话的持久化存储，支持三种模式：
- single: 单文档深度对话（每个 PDF 一个会话）
- cross: 跨文档智能对话（多个会话）
- manual: 跨文档手动选择模式（多个会话）
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class SessionManager:
    """会话管理器"""

    def __init__(self, base_dir: str = "data/sessions"):
        """
        初始化会话管理器

        Args:
            base_dir: 会话数据根目录
        """
        self.base_dir = Path(base_dir)
        self.single_dir = self.base_dir / "single"
        self.cross_dir = self.base_dir / "cross"
        self.manual_dir = self.base_dir / "manual"
        self.metadata_file = self.base_dir / "metadata.json"

        # 确保目录存在
        self._ensure_directories()

        # 加载元数据
        self.metadata = self._load_metadata()

    def _ensure_directories(self):
        """确保所有必要的目录存在"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.single_dir.mkdir(exist_ok=True)
        self.cross_dir.mkdir(exist_ok=True)
        self.manual_dir.mkdir(exist_ok=True)

    def _load_metadata(self) -> Dict:
        """加载元数据"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载元数据失败: {e}")
                return {}
        return {}

    def _save_metadata(self):
        """保存元数据"""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存元数据失败: {e}")

    def _get_session_dir(self, mode: str) -> Path:
        """获取指定模式的会话目录"""
        if mode == "single":
            return self.single_dir
        elif mode == "cross":
            return self.cross_dir
        elif mode == "manual":
            return self.manual_dir
        else:
            raise ValueError(f"无效的模式: {mode}")

    def _get_session_path(self, mode: str, identifier: str) -> Path:
        """
        获取会话文件路径

        Args:
            mode: 会话模式
            identifier: 会话标识符（single 模式为 doc_name，其他为 session_id）
        """
        session_dir = self._get_session_dir(mode)
        return session_dir / f"{identifier}.json"

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
        为单文档模式创建或加载会话（自动加载逻辑）

        Args:
            doc_name: 文档名称

        Returns:
            会话数据
        """
        session_path = self._get_session_path("single", doc_name)

        # 尝试加载现有会话
        existing_session = self._load_session_file(session_path)
        if existing_session:
            logger.info(f"加载现有单文档会话: {doc_name}")
            return existing_session

        # 创建新会话
        logger.info(f"创建新单文档会话: {doc_name}")
        session_data = {
            "session_id": str(uuid.uuid4()),
            "mode": "single",
            "doc_name": doc_name,
            "selected_docs": None,
            "title": f"单文档对话: {doc_name}",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "message_count": 0,
            "messages": []
        }

        self._save_session_file(session_path, session_data)
        return session_data

    def create_session(
        self,
        mode: str,
        doc_name: Optional[str] = None,
        selected_docs: Optional[List[str]] = None,
        title: Optional[str] = None
    ) -> Dict:
        """
        创建新会话（用于 cross 和 manual 模式）

        Args:
            mode: 会话模式 (cross/manual)
            doc_name: 文档名称（single 模式使用）
            selected_docs: 选中的文档列表（manual 模式使用）
            title: 会话标题（可选，自动生成）

        Returns:
            会话数据
        """
        if mode == "single":
            # Single 模式应该使用 create_or_load_single_session
            return self.create_or_load_single_session(doc_name)

        session_id = str(uuid.uuid4())

        # 生成标题
        if not title:
            if mode == "cross":
                title = f"跨文档对话 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            elif mode == "manual":
                doc_count = len(selected_docs) if selected_docs else 0
                title = f"手动选择模式 ({doc_count}个文档) - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        session_data = {
            "session_id": session_id,
            "mode": mode,
            "doc_name": doc_name,
            "selected_docs": selected_docs,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "message_count": 0,
            "messages": []
        }

        session_path = self._get_session_path(mode, session_id)
        self._save_session_file(session_path, session_data)

        logger.info(f"创建新会话: {mode} - {session_id}")
        return session_data

    def load_session(self, session_id: str, mode: str) -> Optional[Dict]:
        """
        加载指定会话

        Args:
            session_id: 会话ID（或 single 模式的 doc_name）
            mode: 会话模式

        Returns:
            会话数据，如果不存在返回 None
        """
        # 对于 single 模式，需要特殊处理：
        # 文件名是 doc_name.json，但传入的可能是 session_id
        # 需要遍历找到匹配的文件
        if mode == "single":
            session_dir = self._get_session_dir(mode)

            # 首先尝试直接加载（如果传入的就是 doc_name）
            session_path = self._get_session_path(mode, session_id)
            session_data = self._load_session_file(session_path)
            if session_data:
                logger.info(f"加载会话: {mode} - {session_id}")
                return session_data

            # 如果直接加载失败，遍历所有 json 文件，找到 session_id 匹配的
            for file_path in session_dir.glob("*.json"):
                try:
                    session_data = self._load_session_file(file_path)
                    if session_data and session_data.get("session_id") == session_id:
                        logger.info(f"加载会话: {mode} - {session_id} (文件: {file_path.name})")
                        return session_data
                except Exception as e:
                    logger.warning(f"读取会话文件失败 {file_path}: {e}")
                    continue

            logger.warning(f"会话不存在: {mode} - {session_id}")
            return None
        else:
            # cross 和 manual 模式：文件名就是 session_id
            session_path = self._get_session_path(mode, session_id)
            session_data = self._load_session_file(session_path)

            if session_data:
                logger.info(f"加载会话: {mode} - {session_id}")
            else:
                logger.warning(f"会话不存在: {mode} - {session_id}")

            return session_data

    def save_message(
        self,
        session_id: str,
        mode: str,
        role: str,
        content: str,
        references: Optional[List] = None,
        doc_name: Optional[str] = None
    ):
        """
        保存消息到会话

        Args:
            session_id: 会话ID（或 single 模式的 doc_name）
            mode: 会话模式
            role: 消息角色 (user/assistant)
            content: 消息内容
            references: 引用信息（可选）
            doc_name: 文档名称（用于 single 模式标识符）
        """
        # Single 模式使用 doc_name 作为标识符
        identifier = doc_name if mode == "single" else session_id

        session_path = self._get_session_path(mode, identifier)
        session_data = self._load_session_file(session_path)

        if not session_data:
            logger.error(f"会话不存在，无法保存消息: {mode} - {identifier}")
            return

        # 添加消息
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        if references:
            message["references"] = references

        session_data["messages"].append(message)
        session_data["message_count"] = len(session_data["messages"])
        session_data["updated_at"] = datetime.now().isoformat()

        # 保存
        self._save_session_file(session_path, session_data)
        logger.debug(f"保存消息到会话: {mode} - {identifier} - {role}")

    def get_session_history_for_llm(self, session: Dict) -> List[Dict[str, str]]:
        """
        将会话历史转换为 LLM 可用的格式

        Args:
            session: 会话数据

        Returns:
            LLM 历史格式 [{"role": "user", "content": "..."}, ...]
        """
        history = []
        for msg in session.get("messages", []):
            history.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        return history

    def list_sessions(self, mode: str, limit: Optional[int] = None) -> List[Dict]:
        """
        列出指定模式的所有会话

        Args:
            mode: 会话模式
            limit: 限制返回数量（可选）

        Returns:
            会话列表（按更新时间倒序）
        """
        session_dir = self._get_session_dir(mode)
        sessions = []

        for session_file in session_dir.glob("*.json"):
            session_data = self._load_session_file(session_file)
            if session_data:
                # 只返回摘要信息，不包含完整消息
                summary = {
                    "session_id": session_data.get("session_id"),
                    "mode": session_data.get("mode"),
                    "doc_name": session_data.get("doc_name"),
                    "selected_docs": session_data.get("selected_docs"),
                    "title": session_data.get("title"),
                    "created_at": session_data.get("created_at"),
                    "updated_at": session_data.get("updated_at"),
                    "message_count": session_data.get("message_count", 0)
                }
                sessions.append(summary)

        # 按更新时间倒序排序
        sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

        if limit:
            sessions = sessions[:limit]

        return sessions

    def delete_session(self, session_id: str, mode: str):
        """
        删除指定会话

        Args:
            session_id: 会话ID（或 single 模式的 doc_name）
            mode: 会话模式
        """
        # 对于 single 模式，需要特殊处理：
        # 文件名是 doc_name.json，但传入的是 session_id
        # 需要遍历找到匹配的文件
        if mode == "single":
            session_dir = self._get_session_dir(mode)
            session_path = None

            # 遍历所有 json 文件，找到 session_id 匹配的
            for file_path in session_dir.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)
                        if session_data.get("session_id") == session_id:
                            session_path = file_path
                            break
                except Exception as e:
                    logger.warning(f"读取会话文件失败 {file_path}: {e}")
                    continue

            if not session_path:
                error_msg = f"会话不存在: {mode} - {session_id}"
                logger.error(f"❌ {error_msg}")
                raise FileNotFoundError(error_msg)

            # 删除找到的文件
            try:
                session_path.unlink()
                logger.info(f"✅ 删除会话: {mode} - {session_id} (文件: {session_path.name})")
            except Exception as e:
                logger.error(f"❌ 删除会话失败: {e}")
                raise
        else:
            # cross 和 manual 模式：文件名就是 session_id
            session_path = self._get_session_path(mode, session_id)

            if session_path.exists():
                try:
                    session_path.unlink()
                    logger.info(f"✅ 删除会话: {mode} - {session_id} ({session_path.name})")
                except Exception as e:
                    logger.error(f"❌ 删除会话失败: {e}")
                    raise
            else:
                error_msg = f"会话文件不存在，无法删除: {mode} - {session_id} (expected: {session_path})"
                logger.error(f"❌ {error_msg}")
                raise FileNotFoundError(error_msg)

    def clear_sessions(self, mode: str):
        """
        清空指定模式的所有会话

        Args:
            mode: 会话模式
        """
        session_dir = self._get_session_dir(mode)

        for session_file in session_dir.glob("*.json"):
            try:
                session_file.unlink()
            except Exception as e:
                logger.error(f"删除会话文件失败 {session_file}: {e}")

        logger.info(f"清空会话: {mode}")
