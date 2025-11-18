"""会话管理服务"""

import json
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4

from ..config import settings, get_logger
from ..core.exceptions import SessionNotFoundError, ServiceError
from ..models.session import SessionModel, SessionCreate, SessionUpdate, ChatMessage

logger = get_logger(__name__)


class SessionService:
    """会话管理服务"""

    def __init__(self):
        self.sessions_dir = settings.sessions_dir
        self.backups_dir = self.sessions_dir / "backups"
        self.exports_dir = self.sessions_dir / "exports"
        # 🔥 新设计：自动保存的会话存储在backups文件夹中
        self.sessions_file = self.backups_dir / "chat_sessions_current.json"

        # 确保目录存在
        self._ensure_directories()

        # 内存中的会话数据
        self._sessions_cache: Dict[str, SessionModel] = {}

        # 加载现有数据 - 从backups文件夹加载
        self.load_sessions_from_backups()

    def _ensure_directories(self):
        """确保目录存在"""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(exist_ok=True)
        self.exports_dir.mkdir(exist_ok=True)

    def load_sessions_from_backups(self) -> bool:
        """从backups文件夹加载会话数据"""
        try:
            # 🔥 新逻辑：优先从旧位置迁移数据
            old_sessions_file = self.sessions_dir / "chat_sessions.json"
            if old_sessions_file.exists() and not self.sessions_file.exists():
                logger.info("发现旧版本会话文件，正在迁移到新位置")
                shutil.copy2(old_sessions_file, self.sessions_file)
                old_sessions_file.unlink()  # 删除旧文件
                logger.info("会话文件迁移完成")

            # 检查当前文件是否存在
            if not self.sessions_file.exists():
                logger.info("会话文件不存在，尝试从备份中恢复最新会话")
                # 查找最新的备份文件
                latest_backup = self._find_latest_backup()
                if latest_backup:
                    logger.info(f"找到最新备份文件: {latest_backup.name}")
                    return self._load_from_backup_file(latest_backup)
                else:
                    logger.info("未找到备份文件，创建新的会话存储")
                    return True

            # 从当前文件加载
            return self._load_from_backup_file(self.sessions_file)

        except Exception as e:
            logger.error(f"从备份加载会话失败: {e}")
            return False

    def _find_latest_backup(self):
        """查找最新的备份文件"""
        try:
            backup_files = list(self.backups_dir.glob("chat_sessions_backup_*.json"))
            if not backup_files:
                return None

            # 按修改时间排序，返回最新的
            backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            return backup_files[0]
        except Exception as e:
            logger.error(f"查找备份文件失败: {e}")
            return None

    def _load_from_backup_file(self, file_path) -> bool:
        """从指定备份文件加载会话数据"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 验证数据结构
            if not isinstance(data, dict) or "sessions" not in data:
                logger.warning(f"文件格式无效: {file_path.name}")
                return False

            # 加载会话到缓存
            sessions_data = data.get("sessions", {})
            for session_id, session_dict in sessions_data.items():
                try:
                    # 转换消息格式
                    messages = []
                    for msg in session_dict.get("messages", []):
                        if isinstance(msg, list) and len(msg) >= 3:
                            messages.append(ChatMessage(
                                role=msg[0],
                                content=msg[1],
                                timestamp=msg[2]
                            ))

                    # 创建会话模型
                    session = SessionModel(
                        chat_id=session_dict.get("chatId", session_id),
                        doc_name=session_dict.get("docName"),
                        has_pdf_reader=session_dict.get("hasPdfReader", False),
                        has_web_reader=session_dict.get("hasWebReader", False),
                        provider=session_dict.get("provider", "openai"),
                        messages=messages,
                        timestamp=session_dict.get("timestamp", datetime.now().timestamp() * 1000),
                        created_at=datetime.fromisoformat(
                            session_dict.get("created_at", datetime.now().isoformat())
                        ),
                        updated_at=datetime.fromisoformat(
                            session_dict.get("updated_at", datetime.now().isoformat())
                        )
                    )

                    self._sessions_cache[session_id] = session

                except Exception as e:
                    logger.error(f"加载会话 {session_id} 失败: {e}")
                    continue

            logger.info(f"从 {file_path.name} 成功加载 {len(self._sessions_cache)} 个会话")
            return True

        except Exception as e:
            logger.error(f"加载文件失败 {file_path}: {e}")
            return False

    def save_sessions(self, create_backup: bool = True) -> bool:
        """保存会话数据到文件"""
        try:
            # 创建备份
            if create_backup and self.sessions_file.exists():
                self._create_backup()

            # 准备保存数据
            sessions_data = {}
            for session_id, session in self._sessions_cache.items():
                sessions_data[session_id] = session.to_dict()

            save_data = {
                "sessions": sessions_data,
                "metadata": {
                    "created_at": datetime.now().isoformat(),
                    "last_updated": datetime.now().isoformat(),
                    "version": "1.0",
                    "total_sessions": len(sessions_data)
                }
            }

            # 保存主文件
            with open(self.sessions_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)

            logger.info(f"成功保存 {len(sessions_data)} 个会话")
            return True

        except Exception as e:
            logger.error(f"保存会话文件失败: {e}")
            return False

    def _create_backup(self):
        """创建备份文件 - 将当前会话文件备份并创建新的时间戳备份"""
        try:
            # 🔥 新逻辑：创建带时间戳的备份文件
            backup_name = f"chat_sessions_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            backup_path = self.backups_dir / backup_name

            # 如果当前文件存在，创建备份
            if self.sessions_file.exists():
                shutil.copy2(self.sessions_file, backup_path)
                logger.info(f"创建备份: {backup_name}")

            # 清理旧备份，保留最近的10个
            self._cleanup_backups()

        except Exception as e:
            logger.warning(f"创建备份失败: {e}")

    def _cleanup_backups(self, keep_count: int = None):
        """清理旧备份文件"""
        try:
            if keep_count is None:
                keep_count = settings.max_backup_files

            backup_files = list(self.backups_dir.glob("chat_sessions_backup_*.json"))
            if len(backup_files) > keep_count:
                # 按修改时间排序，删除最旧的文件
                backup_files.sort(key=lambda x: x.stat().st_mtime)
                for old_backup in backup_files[:-keep_count]:
                    old_backup.unlink()
                    logger.info(f"清理旧备份: {old_backup.name}")

        except Exception as e:
            logger.warning(f"清理备份失败: {e}")

    def create_session(self, session_data: SessionCreate) -> SessionModel:
        """创建新会话"""
        try:
            session_id = str(uuid4())
            now = datetime.now()

            session = SessionModel(
                chat_id=session_id,
                doc_name=session_data.doc_name,
                has_pdf_reader=session_data.has_pdf_reader,
                has_web_reader=session_data.has_web_reader,
                provider=session_data.provider,
                messages=[],
                timestamp=now.timestamp() * 1000,
                created_at=now,
                updated_at=now
            )

            self._sessions_cache[session_id] = session
            logger.info(f"创建新会话: {session_id}")

            return session

        except Exception as e:
            raise ServiceError("SessionService", "create_session", str(e))

    def get_session(self, session_id: str) -> SessionModel:
        """获取指定会话"""
        if session_id not in self._sessions_cache:
            raise SessionNotFoundError(session_id)

        return self._sessions_cache[session_id]

    def update_session(self, session_id: str, session_data: SessionUpdate) -> SessionModel:
        """更新会话"""
        if session_id not in self._sessions_cache:
            raise SessionNotFoundError(session_id)

        session = self._sessions_cache[session_id]

        # 更新字段
        if session_data.doc_name is not None:
            session.doc_name = session_data.doc_name
        if session_data.provider is not None:
            session.provider = session_data.provider
        if session_data.has_pdf_reader is not None:
            session.has_pdf_reader = session_data.has_pdf_reader
        if session_data.has_web_reader is not None:
            session.has_web_reader = session_data.has_web_reader
        if session_data.messages is not None:
            session.messages = session_data.messages

        session.updated_at = datetime.now()

        logger.info(f"更新会话: {session_id}")
        return session

    def delete_session(self, session_id: str) -> bool:
        """删除指定会话"""
        if session_id not in self._sessions_cache:
            raise SessionNotFoundError(session_id)

        del self._sessions_cache[session_id]
        logger.info(f"删除会话: {session_id}")
        return True

    def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """获取所有会话"""
        sessions_dict = {}
        for session_id, session in self._sessions_cache.items():
            sessions_dict[session_id] = session.to_dict()

        return sessions_dict

    def clear_all_sessions(self) -> bool:
        """清空所有会话并删除备份文件"""
        try:
            # 清空内存中的会话缓存
            self._sessions_cache.clear()

            # 🔥 新增：删除主会话文件
            if self.sessions_file.exists():
                self.sessions_file.unlink()
                logger.info(f"删除主会话文件: {self.sessions_file}")

            # 🔥 新增：删除所有备份文件
            if self.backups_dir.exists():
                backup_files = list(self.backups_dir.glob("chat_sessions_backup_*.json"))
                for backup_file in backup_files:
                    try:
                        backup_file.unlink()
                        logger.info(f"删除备份文件: {backup_file.name}")
                    except Exception as e:
                        logger.warning(f"删除备份文件失败 {backup_file.name}: {e}")

                logger.info(f"删除了 {len(backup_files)} 个备份文件")

            logger.info("清空所有会话和备份文件完成")
            return True
        except Exception as e:
            logger.error(f"清空会话失败: {e}")
            return False

    def cleanup_meaningless_sessions(self) -> int:
        """清理无意义的会话"""
        try:
            sessions_to_delete = []

            for session_id, session in self._sessions_cache.items():
                if not session.is_meaningful():
                    sessions_to_delete.append(session_id)

            # 删除无意义会话
            for session_id in sessions_to_delete:
                del self._sessions_cache[session_id]

            if sessions_to_delete:
                logger.info(f"清理了 {len(sessions_to_delete)} 个无意义会话")

            return len(sessions_to_delete)

        except Exception as e:
            logger.error(f"清理无意义会话失败: {e}")
            return 0

    def export_sessions(self, filename: Optional[str] = None) -> str:
        """导出会话数据"""
        try:
            if not filename:
                filename = f"sessions_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

            export_path = self.exports_dir / filename

            # 准备导出数据
            export_data = {
                "export_info": {
                    "exported_at": datetime.now().isoformat(),
                    "total_sessions": len(self._sessions_cache),
                    "version": "1.0"
                },
                "sessions": self.get_all_sessions()
            }

            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

            logger.info(f"导出会话到: {filename}")
            return str(export_path)

        except Exception as e:
            logger.error(f"导出会话失败: {e}")
            raise ServiceError("SessionService", "export_sessions", str(e))

    def import_sessions(self, file_path: str, merge: bool = True) -> bool:
        """导入会话数据"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                import_data = json.load(f)

            # 验证导入数据格式
            if not isinstance(import_data, dict) or "sessions" not in import_data:
                raise ValueError("导入文件格式无效")

            imported_sessions_data = import_data["sessions"]

            if not merge:
                # 替换模式: 清空现有会话
                self._sessions_cache.clear()

            # 导入会话
            for session_id, session_dict in imported_sessions_data.items():
                try:
                    # 转换消息格式
                    messages = []
                    for msg in session_dict.get("messages", []):
                        if isinstance(msg, list) and len(msg) >= 3:
                            messages.append(ChatMessage(
                                role=msg[0],
                                content=msg[1],
                                timestamp=msg[2]
                            ))

                    # 创建会话模型
                    session = SessionModel(
                        chat_id=session_dict.get("chatId", session_id),
                        doc_name=session_dict.get("docName"),
                        has_pdf_reader=session_dict.get("hasPdfReader", False),
                        has_web_reader=session_dict.get("hasWebReader", False),
                        provider=session_dict.get("provider", "openai"),
                        messages=messages,
                        timestamp=session_dict.get("timestamp", datetime.now().timestamp() * 1000),
                        created_at=datetime.fromisoformat(
                            session_dict.get("created_at", datetime.now().isoformat())
                        ),
                        updated_at=datetime.fromisoformat(
                            session_dict.get("updated_at", datetime.now().isoformat())
                        )
                    )

                    self._sessions_cache[session_id] = session

                except Exception as e:
                    logger.error(f"导入会话 {session_id} 失败: {e}")
                    continue

            mode = "合并" if merge else "替换"
            logger.info(f"{mode}导入 {len(imported_sessions_data)} 个会话")
            return True

        except Exception as e:
            logger.error(f"导入会话失败: {e}")
            return False