"""数据管理服务"""

import os
import shutil
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from ..config import settings, get_logger

logger = get_logger(__name__)


class DataService:
    """数据管理服务，负责文件系统操作"""

    def __init__(self):
        self.data_root = settings.project_root / "data"
        self.pdf_dir = self.data_root / "pdf"
        self.pdf_image_dir = self.data_root / "pdf_image"
        self.json_data_dir = self.data_root / "json_data"
        self.vector_db_dir = self.data_root / "vector_db"
        self.output_dir = self.data_root / "output"
        self.sessions_dir = self.data_root / "sessions"

    def _get_dir_size(self, path: Path) -> int:
        """计算目录大小(字节)"""
        total = 0
        try:
            if path.exists():
                for entry in path.rglob('*'):
                    if entry.is_file():
                        total += entry.stat().st_size
        except Exception as e:
            logger.warning(f"计算目录大小失败 {path}: {e}")
        return total

    def _format_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"

    def _count_files(self, path: Path, pattern: str = "*") -> int:
        """统计文件数量"""
        try:
            if path.exists():
                return len(list(path.glob(pattern)))
        except Exception as e:
            logger.warning(f"统计文件数量失败 {path}: {e}")
        return 0

    async def get_storage_overview(self) -> Dict[str, Any]:
        """获取存储概览"""
        try:
            # 统计已处理的文档数量(通过output目录判断)
            documents = list(self.output_dir.glob("*")) if self.output_dir.exists() else []
            doc_count = len([d for d in documents if d.is_dir()])

            # 计算总存储大小
            total_size = sum([
                self._get_dir_size(self.pdf_dir),
                self._get_dir_size(self.pdf_image_dir),
                self._get_dir_size(self.json_data_dir),
                self._get_dir_size(self.vector_db_dir),
                self._get_dir_size(self.output_dir),
            ])

            # 统计会话数量
            sessions_file = self.sessions_dir / "backups" / "chat_sessions_current.json"
            session_count = 0
            if sessions_file.exists():
                try:
                    with open(sessions_file, 'r', encoding='utf-8') as f:
                        sessions_data = json.load(f)
                        session_count = len(sessions_data.get("sessions", []))
                except Exception as e:
                    logger.warning(f"读取会话文件失败: {e}")

            # 上次清理时间(从缓存文件读取或使用默认值)
            cleanup_file = self.data_root / "config" / "last_cleanup.txt"
            last_cleanup = "从未"
            if cleanup_file.exists():
                try:
                    last_cleanup = cleanup_file.read_text().strip()
                except:
                    pass

            return {
                "total_documents": doc_count,
                "total_size": self._format_size(total_size),
                "total_size_bytes": total_size,
                "chat_sessions": session_count,
                "last_cleanup": last_cleanup
            }
        except Exception as e:
            logger.error(f"获取存储概览失败: {e}")
            raise

    async def list_documents(self) -> List[Dict[str, Any]]:
        """列出所有已处理的文档"""
        try:
            documents = []

            # 从output目录获取已处理的文档
            if self.output_dir.exists():
                for doc_dir in self.output_dir.iterdir():
                    if not doc_dir.is_dir():
                        continue

                    doc_name = doc_dir.name

                    # 获取详细的数据信息
                    json_folder = self.json_data_dir / doc_name  # JSON文件夹
                    vector_db_path = self.vector_db_dir / f"{doc_name}_data_index"
                    images_path = self.pdf_image_dir / doc_name

                    # 获取文档信息
                    doc_info = {
                        "name": doc_name,
                        "has_json": json_folder.exists(),
                        "has_vector_db": vector_db_path.exists(),
                        "has_images": images_path.exists(),
                        "has_summary": False,
                        "output_files": [],
                        "created_time": None,
                        "modified_time": None,
                        "size": 0,
                        # 新增：详细的数据大小信息
                        "data_details": {
                            "json": {
                                "size": self._get_dir_size(json_folder) if json_folder.exists() else 0,
                                "size_formatted": self._format_size(self._get_dir_size(json_folder)) if json_folder.exists() else "0 B"
                            },
                            "vector_db": {
                                "size": self._get_dir_size(vector_db_path) if vector_db_path.exists() else 0,
                                "size_formatted": self._format_size(self._get_dir_size(vector_db_path)) if vector_db_path.exists() else "0 B"
                            },
                            "images": {
                                "size": self._get_dir_size(images_path) if images_path.exists() else 0,
                                "size_formatted": self._format_size(self._get_dir_size(images_path)) if images_path.exists() else "0 B",
                                "count": len(list(images_path.glob("*"))) if images_path.exists() else 0
                            },
                            "summary": {
                                "size": 0,
                                "size_formatted": "0 B",
                                "files": []
                            }
                        }
                    }

                    # 统计output文件
                    for file in doc_dir.glob("*"):
                        if file.is_file():
                            doc_info["output_files"].append(file.name)
                            file_size = file.stat().st_size
                            doc_info["size"] += file_size

                            if "summary" in file.name:
                                doc_info["has_summary"] = True
                                doc_info["data_details"]["summary"]["size"] += file_size
                                doc_info["data_details"]["summary"]["files"].append({
                                    "name": file.name,
                                    "size": file_size,
                                    "size_formatted": self._format_size(file_size)
                                })

                    doc_info["data_details"]["summary"]["size_formatted"] = self._format_size(
                        doc_info["data_details"]["summary"]["size"]
                    )

                    # 获取时间信息
                    try:
                        stat = doc_dir.stat()
                        doc_info["created_time"] = datetime.fromtimestamp(stat.st_ctime).isoformat()
                        doc_info["modified_time"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    except:
                        pass

                    doc_info["size_formatted"] = self._format_size(doc_info["size"])
                    documents.append(doc_info)

            # 按修改时间排序
            documents.sort(key=lambda x: x.get("modified_time", ""), reverse=True)
            return documents

        except Exception as e:
            logger.error(f"列出文档失败: {e}")
            raise

    async def get_cache_info(self, cache_type: str) -> Dict[str, Any]:
        """获取缓存信息"""
        try:
            cache_map = {
                "pdf_image": self.pdf_image_dir,
                "vector_db": self.vector_db_dir,
                "json_data": self.json_data_dir
            }

            if cache_type not in cache_map:
                raise ValueError(f"未知的缓存类型: {cache_type}")

            cache_dir = cache_map[cache_type]
            items = []

            if cache_dir.exists():
                for item in cache_dir.iterdir():
                    item_info = {
                        "name": item.name,
                        "size": 0,
                        "modified_time": None,
                        "is_dir": item.is_dir()
                    }

                    if item.is_dir():
                        item_info["size"] = self._get_dir_size(item)
                    else:
                        item_info["size"] = item.stat().st_size

                    try:
                        stat = item.stat()
                        item_info["modified_time"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    except:
                        pass

                    item_info["size_formatted"] = self._format_size(item_info["size"])
                    items.append(item_info)

            total_size = sum(item["size"] for item in items)

            return {
                "cache_type": cache_type,
                "items": items,
                "total_count": len(items),
                "total_size": self._format_size(total_size),
                "total_size_bytes": total_size
            }

        except Exception as e:
            logger.error(f"获取缓存信息失败: {e}")
            raise

    async def delete_document_data(
        self,
        document_name: str,
        data_types: List[str]
    ) -> Dict[str, Any]:
        """删除文档的特定数据类型

        Args:
            document_name: 文档名称
            data_types: 要删除的数据类型列表 ['json', 'vector_db', 'images', 'summary', 'all']
        """
        try:
            deleted = []
            failed = []
            total_freed = 0

            # 定义数据类型到路径的映射
            data_type_paths = {
                "json": self.json_data_dir / f"{document_name}.json",
                "vector_db": self.vector_db_dir / f"{document_name}_data_index",
                "images": self.pdf_image_dir / document_name,
                "summary": self.output_dir / document_name  # summary文件在output目录下
            }

            # 处理'all'类型
            if "all" in data_types:
                data_types = list(data_type_paths.keys())

            for data_type in data_types:
                if data_type not in data_type_paths:
                    failed.append({"type": data_type, "reason": "未知的数据类型"})
                    continue

                path = data_type_paths[data_type]

                try:
                    if data_type == "summary":
                        # summary需要特殊处理，只删除summary相关文件
                        if path.exists() and path.is_dir():
                            summary_files = list(path.glob("*summary*"))
                            for file in summary_files:
                                size = file.stat().st_size
                                file.unlink()
                                total_freed += size

                            if summary_files:
                                deleted.append({
                                    "type": data_type,
                                    "count": len(summary_files),
                                    "files": [f.name for f in summary_files]
                                })
                            else:
                                failed.append({"type": data_type, "reason": "无summary文件"})
                    else:
                        # 其他类型直接删除
                        if path.exists():
                            if path.is_dir():
                                size = self._get_dir_size(path)
                                shutil.rmtree(path)
                            else:
                                size = path.stat().st_size
                                path.unlink()

                            total_freed += size
                            deleted.append({"type": data_type, "freed": self._format_size(size)})
                            logger.info(f"已删除 {document_name} 的 {data_type} 数据")
                        else:
                            failed.append({"type": data_type, "reason": "数据不存在"})

                except Exception as e:
                    logger.error(f"删除 {document_name} 的 {data_type} 失败: {e}")
                    failed.append({"type": data_type, "reason": str(e)})

            return {
                "document": document_name,
                "deleted": deleted,
                "failed": failed,
                "total_freed": self._format_size(total_freed),
                "total_freed_bytes": total_freed
            }

        except Exception as e:
            logger.error(f"删除文档数据失败: {e}")
            raise

    async def delete_documents(self, document_names: List[str]) -> Dict[str, Any]:
        """批量删除文档及其相关数据"""
        try:
            deleted = []
            failed = []

            for doc_name in document_names:
                try:
                    # 删除各个位置的数据
                    paths_to_delete = [
                        self.output_dir / doc_name,
                        self.json_data_dir / doc_name,  # JSON文件夹
                        self.vector_db_dir / f"{doc_name}_data_index",
                        self.pdf_image_dir / doc_name
                    ]

                    deleted_count = 0
                    for path in paths_to_delete:
                        if path.exists():
                            if path.is_dir():
                                shutil.rmtree(path)
                            else:
                                path.unlink()
                            deleted_count += 1

                    if deleted_count > 0:
                        deleted.append(doc_name)
                        logger.info(f"已删除文档: {doc_name}")
                    else:
                        failed.append({"name": doc_name, "reason": "文档不存在"})

                except Exception as e:
                    logger.error(f"删除文档失败 {doc_name}: {e}")
                    failed.append({"name": doc_name, "reason": str(e)})

            return {
                "deleted": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed)
            }

        except Exception as e:
            logger.error(f"批量删除文档失败: {e}")
            raise

    async def clear_cache(self, cache_type: str, items: Optional[List[str]] = None) -> Dict[str, Any]:
        """清理缓存"""
        try:
            cache_map = {
                "pdf_image": self.pdf_image_dir,
                "vector_db": self.vector_db_dir,
                "json_data": self.json_data_dir
            }

            deleted_count = 0
            deleted_size = 0

            if cache_type == "all":
                # 清空所有缓存
                for cache_dir in cache_map.values():
                    if cache_dir.exists():
                        for item in cache_dir.iterdir():
                            size = self._get_dir_size(item) if item.is_dir() else item.stat().st_size
                            if item.is_dir():
                                shutil.rmtree(item)
                            else:
                                item.unlink()
                            deleted_count += 1
                            deleted_size += size
            else:
                if cache_type not in cache_map:
                    raise ValueError(f"未知的缓存类型: {cache_type}")

                cache_dir = cache_map[cache_type]

                if items is None:
                    # 清空指定类型的所有缓存
                    if cache_dir.exists():
                        for item in cache_dir.iterdir():
                            size = self._get_dir_size(item) if item.is_dir() else item.stat().st_size
                            if item.is_dir():
                                shutil.rmtree(item)
                            else:
                                item.unlink()
                            deleted_count += 1
                            deleted_size += size
                else:
                    # 删除指定的项目
                    for item_name in items:
                        item_path = cache_dir / item_name
                        if item_path.exists():
                            size = self._get_dir_size(item_path) if item_path.is_dir() else item_path.stat().st_size
                            if item_path.is_dir():
                                shutil.rmtree(item_path)
                            else:
                                item_path.unlink()
                            deleted_count += 1
                            deleted_size += size

            return {
                "deleted_count": deleted_count,
                "deleted_size": self._format_size(deleted_size),
                "deleted_size_bytes": deleted_size
            }

        except Exception as e:
            logger.error(f"清理缓存失败: {e}")
            raise

    async def smart_cleanup(self, days: int = 30) -> Dict[str, Any]:
        """智能清理超过指定天数的数据"""
        try:
            cutoff_time = datetime.now() - timedelta(days=days)
            deleted_files = []
            total_freed = 0

            # 检查各个目录
            dirs_to_check = [
                self.pdf_image_dir,
                self.json_data_dir,
                self.vector_db_dir,
                self.output_dir
            ]

            for check_dir in dirs_to_check:
                if not check_dir.exists():
                    continue

                for item in check_dir.iterdir():
                    try:
                        # 检查修改时间
                        mtime = datetime.fromtimestamp(item.stat().st_mtime)
                        if mtime < cutoff_time:
                            size = self._get_dir_size(item) if item.is_dir() else item.stat().st_size

                            if item.is_dir():
                                shutil.rmtree(item)
                            else:
                                item.unlink()

                            deleted_files.append({
                                "name": item.name,
                                "path": str(item.relative_to(self.data_root)),
                                "size": self._format_size(size),
                                "modified_time": mtime.isoformat()
                            })
                            total_freed += size
                    except Exception as e:
                        logger.warning(f"清理文件失败 {item}: {e}")

            # 记录清理时间
            cleanup_file = self.data_root / "config" / "last_cleanup.txt"
            cleanup_file.parent.mkdir(exist_ok=True)
            cleanup_file.write_text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            return {
                "deleted_files": deleted_files,
                "deleted_count": len(deleted_files),
                "total_freed": self._format_size(total_freed),
                "total_freed_bytes": total_freed,
                "cutoff_days": days
            }

        except Exception as e:
            logger.error(f"智能清理失败: {e}")
            raise

    async def create_backup(self) -> str:
        """创建数据备份"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = self.data_root / "backups" / f"backup_{timestamp}"
            backup_dir.mkdir(parents=True, exist_ok=True)

            # 备份重要数据
            important_dirs = [
                ("sessions", self.sessions_dir),
                ("output", self.output_dir),
                ("config", self.data_root / "config")
            ]

            for name, src_dir in important_dirs:
                if src_dir.exists():
                    dst_dir = backup_dir / name
                    shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)

            logger.info(f"备份创建成功: {backup_dir}")
            return str(backup_dir.relative_to(self.data_root))

        except Exception as e:
            logger.error(f"创建备份失败: {e}")
            raise

    async def full_reset(self) -> Dict[str, Any]:
        """完全重置所有数据"""
        try:
            deleted_dirs = []

            # 删除所有数据目录（保留sessions/backups作为最后的保险）
            dirs_to_delete = [
                self.pdf_image_dir,
                self.json_data_dir,
                self.vector_db_dir,
                self.output_dir,
                self.pdf_dir
            ]

            for dir_path in dirs_to_delete:
                if dir_path.exists():
                    shutil.rmtree(dir_path)
                    dir_path.mkdir(exist_ok=True)
                    deleted_dirs.append(str(dir_path.relative_to(self.data_root)))

            logger.warning("已执行完全重置操作")

            return {
                "deleted_dirs": deleted_dirs,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"完全重置失败: {e}")
            raise

    async def get_session_stats(self) -> Dict[str, Any]:
        """获取会话统计信息"""
        try:
            sessions_file = self.sessions_dir / "backups" / "chat_sessions_current.json"

            stats = {
                "total_sessions": 0,
                "total_messages": 0,
                "last_activity": None,
                "storage_size": 0
            }

            if sessions_file.exists():
                try:
                    with open(sessions_file, 'r', encoding='utf-8') as f:
                        sessions_data = json.load(f)
                        sessions_dict = sessions_data.get("sessions", {})

                        # 处理sessions可能是dict或list的情况
                        if isinstance(sessions_dict, dict):
                            sessions = list(sessions_dict.values())
                        else:
                            sessions = sessions_dict if isinstance(sessions_dict, list) else []

                        stats["total_sessions"] = len(sessions)

                        # 统计消息数量
                        for session in sessions:
                            if isinstance(session, dict):
                                messages = session.get("messages", [])
                                stats["total_messages"] += len(messages)

                        # 获取最后活动时间
                        if sessions:
                            # 尝试从updatedAt或updated_at字段获取
                            last_times = []
                            for s in sessions:
                                if isinstance(s, dict):
                                    time_val = s.get("updatedAt") or s.get("updated_at", "")
                                    if time_val:
                                        last_times.append(time_val)

                            if last_times:
                                stats["last_activity"] = max(last_times)

                    stats["storage_size"] = self._format_size(sessions_file.stat().st_size)

                except Exception as e:
                    logger.warning(f"读取会话统计失败: {e}")

            # 统计备份数量
            backups_dir = self.sessions_dir / "backups"
            if backups_dir.exists():
                backup_files = list(backups_dir.glob("chat_sessions_backup_*.json"))
                stats["backup_count"] = len(backup_files)

            return stats

        except Exception as e:
            logger.error(f"获取会话统计失败: {e}")
            raise
