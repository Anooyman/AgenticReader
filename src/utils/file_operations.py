"""
统一的文件操作工具

提供安全、可靠的文件I/O操作，包含错误处理和验证
"""
import json
import os
import shutil
import tempfile
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, BinaryIO, TextIO
from contextlib import contextmanager

from .exceptions import FileProcessingError, ValidationError
from .validators import validate_file_path, sanitize_filename
from .error_handler import retry_on_error, safe_execute, error_context

logger = logging.getLogger(__name__)


class SafeFileOperations:
    """安全的文件操作类"""

    @staticmethod
    def read_text_file(file_path: str, encoding: str = 'utf-8') -> str:
        """
        安全地读取文本文件

        Args:
            file_path (str): 文件路径
            encoding (str): 文件编码

        Returns:
            str: 文件内容

        Raises:
            FileProcessingError: 文件操作失败
        """
        try:
            validated_path = validate_file_path(file_path, check_exists=True)

            with open(validated_path, 'r', encoding=encoding) as file:
                content = file.read()

            logger.debug(f"成功读取文本文件: {file_path}, 大小: {len(content)} 字符")
            return content

        except ValidationError as e:
            raise FileProcessingError(f"文件路径验证失败: {e}", "INVALID_PATH")
        except FileNotFoundError:
            raise FileProcessingError(f"文件不存在: {file_path}", "FILE_NOT_FOUND")
        except PermissionError:
            raise FileProcessingError(f"无权限读取文件: {file_path}", "PERMISSION_DENIED")
        except UnicodeDecodeError as e:
            raise FileProcessingError(f"文件编码错误: {e}", "ENCODING_ERROR")
        except Exception as e:
            raise FileProcessingError(f"读取文件时发生未知错误: {e}", "UNKNOWN_ERROR")

    @staticmethod
    def write_text_file(file_path: str, content: str, encoding: str = 'utf-8',
                       create_dirs: bool = True) -> None:
        """
        安全地写入文本文件

        Args:
            file_path (str): 文件路径
            content (str): 要写入的内容
            encoding (str): 文件编码
            create_dirs (bool): 是否自动创建目录

        Raises:
            FileProcessingError: 文件操作失败
        """
        try:
            validated_path = validate_file_path(file_path, check_exists=False)
            path_obj = Path(validated_path)

            # 创建目录
            if create_dirs and not path_obj.parent.exists():
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                logger.debug(f"创建目录: {path_obj.parent}")

            # 使用临时文件确保原子性写入
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding=encoding,
                dir=path_obj.parent,
                delete=False
            ) as temp_file:
                temp_file.write(content)
                temp_path = temp_file.name

            # 原子性移动到目标位置
            shutil.move(temp_path, validated_path)
            logger.info(f"成功写入文本文件: {file_path}, 大小: {len(content)} 字符")

        except ValidationError as e:
            raise FileProcessingError(f"文件路径验证失败: {e}", "INVALID_PATH")
        except PermissionError:
            raise FileProcessingError(f"无权限写入文件: {file_path}", "PERMISSION_DENIED")
        except OSError as e:
            raise FileProcessingError(f"文件系统错误: {e}", "FILESYSTEM_ERROR")
        except Exception as e:
            # 清理临时文件
            if 'temp_path' in locals() and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            raise FileProcessingError(f"写入文件时发生未知错误: {e}", "UNKNOWN_ERROR")

    @staticmethod
    def read_json_file(file_path: str) -> Union[Dict[str, Any], List[Any]]:
        """
        安全地读取JSON文件

        Args:
            file_path (str): JSON文件路径

        Returns:
            Union[Dict[str, Any], List[Any]]: 解析后的JSON数据

        Raises:
            FileProcessingError: 文件操作失败
        """
        try:
            content = SafeFileOperations.read_text_file(file_path)
            data = json.loads(content)
            logger.debug(f"成功读取JSON文件: {file_path}")
            return data

        except json.JSONDecodeError as e:
            raise FileProcessingError(f"JSON格式错误: {e}", "JSON_DECODE_ERROR")
        except FileProcessingError:
            raise  # 重新抛出文件操作错误

    @staticmethod
    def write_json_file(file_path: str, data: Union[Dict[str, Any], List[Any]],
                       indent: Optional[int] = 2, ensure_ascii: bool = False) -> None:
        """
        安全地写入JSON文件

        Args:
            file_path (str): JSON文件路径
            data: 要写入的数据
            indent: JSON缩进
            ensure_ascii: 是否确保ASCII编码

        Raises:
            FileProcessingError: 文件操作失败
        """
        try:
            content = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
            SafeFileOperations.write_text_file(file_path, content)
            logger.info(f"成功写入JSON文件: {file_path}")

        except (TypeError, ValueError) as e:
            raise FileProcessingError(f"JSON序列化错误: {e}", "JSON_ENCODE_ERROR")
        except FileProcessingError:
            raise  # 重新抛出文件操作错误

    @staticmethod
    def copy_file(src_path: str, dest_path: str, overwrite: bool = False) -> None:
        """
        安全地复制文件

        Args:
            src_path (str): 源文件路径
            dest_path (str): 目标文件路径
            overwrite (bool): 是否覆盖已存在的文件

        Raises:
            FileProcessingError: 文件操作失败
        """
        try:
            validated_src = validate_file_path(src_path, check_exists=True)
            validated_dest = validate_file_path(dest_path, check_exists=False)

            dest_path_obj = Path(validated_dest)

            # 检查目标文件是否存在
            if dest_path_obj.exists() and not overwrite:
                raise FileProcessingError(f"目标文件已存在: {dest_path}", "FILE_EXISTS")

            # 创建目标目录
            dest_path_obj.parent.mkdir(parents=True, exist_ok=True)

            # 复制文件
            shutil.copy2(validated_src, validated_dest)
            logger.info(f"成功复制文件: {src_path} -> {dest_path}")

        except ValidationError as e:
            raise FileProcessingError(f"文件路径验证失败: {e}", "INVALID_PATH")
        except shutil.Error as e:
            raise FileProcessingError(f"文件复制失败: {e}", "COPY_ERROR")
        except Exception as e:
            raise FileProcessingError(f"复制文件时发生未知错误: {e}", "UNKNOWN_ERROR")

    @staticmethod
    def delete_file(file_path: str, ignore_missing: bool = True) -> bool:
        """
        安全地删除文件

        Args:
            file_path (str): 要删除的文件路径
            ignore_missing (bool): 是否忽略文件不存在的错误

        Returns:
            bool: 是否成功删除

        Raises:
            FileProcessingError: 文件操作失败
        """
        try:
            validated_path = validate_file_path(file_path, check_exists=False)
            path_obj = Path(validated_path)

            if not path_obj.exists():
                if ignore_missing:
                    logger.debug(f"文件不存在，跳过删除: {file_path}")
                    return False
                else:
                    raise FileProcessingError(f"文件不存在: {file_path}", "FILE_NOT_FOUND")

            path_obj.unlink()
            logger.info(f"成功删除文件: {file_path}")
            return True

        except ValidationError as e:
            raise FileProcessingError(f"文件路径验证失败: {e}", "INVALID_PATH")
        except PermissionError:
            raise FileProcessingError(f"无权限删除文件: {file_path}", "PERMISSION_DENIED")
        except Exception as e:
            raise FileProcessingError(f"删除文件时发生未知错误: {e}", "UNKNOWN_ERROR")

    @staticmethod
    def ensure_directory(dir_path: str) -> None:
        """
        确保目录存在

        Args:
            dir_path (str): 目录路径

        Raises:
            FileProcessingError: 目录操作失败
        """
        try:
            validated_path = validate_file_path(dir_path, check_exists=False, is_directory=True)
            path_obj = Path(validated_path)

            if path_obj.exists() and not path_obj.is_dir():
                raise FileProcessingError(f"路径存在但不是目录: {dir_path}", "NOT_DIRECTORY")

            path_obj.mkdir(parents=True, exist_ok=True)
            logger.debug(f"确保目录存在: {dir_path}")

        except ValidationError as e:
            raise FileProcessingError(f"目录路径验证失败: {e}", "INVALID_PATH")
        except PermissionError:
            raise FileProcessingError(f"无权限创建目录: {dir_path}", "PERMISSION_DENIED")
        except Exception as e:
            raise FileProcessingError(f"创建目录时发生未知错误: {e}", "UNKNOWN_ERROR")

    @staticmethod
    def get_file_info(file_path: str) -> Dict[str, Any]:
        """
        获取文件信息

        Args:
            file_path (str): 文件路径

        Returns:
            Dict[str, Any]: 文件信息

        Raises:
            FileProcessingError: 文件操作失败
        """
        try:
            validated_path = validate_file_path(file_path, check_exists=True)
            path_obj = Path(validated_path)
            stat = path_obj.stat()

            return {
                "path": str(path_obj),
                "name": path_obj.name,
                "size": stat.st_size,
                "size_mb": stat.st_size / (1024 * 1024),
                "created": stat.st_ctime,
                "modified": stat.st_mtime,
                "is_file": path_obj.is_file(),
                "is_dir": path_obj.is_dir(),
                "extension": path_obj.suffix,
            }

        except ValidationError as e:
            raise FileProcessingError(f"文件路径验证失败: {e}", "INVALID_PATH")
        except Exception as e:
            raise FileProcessingError(f"获取文件信息时发生错误: {e}", "UNKNOWN_ERROR")


class BatchFileOperations:
    """批量文件操作类"""

    @staticmethod
    def batch_process_files(file_paths: List[str],
                          operation: str,
                          **kwargs) -> Dict[str, Any]:
        """
        批量处理文件

        Args:
            file_paths (List[str]): 文件路径列表
            operation (str): 操作类型 ('read', 'delete', 'copy')
            **kwargs: 操作参数

        Returns:
            Dict[str, Any]: 处理结果统计
        """
        results = {
            "total": len(file_paths),
            "succeeded": 0,
            "failed": 0,
            "errors": []
        }

        for file_path in file_paths:
            try:
                if operation == 'read':
                    SafeFileOperations.read_text_file(file_path)
                elif operation == 'delete':
                    SafeFileOperations.delete_file(file_path, **kwargs)
                elif operation == 'copy':
                    dest_path = kwargs.get('dest_path')
                    if not dest_path:
                        raise ValueError("copy操作需要dest_path参数")
                    SafeFileOperations.copy_file(file_path, dest_path, **kwargs)

                results["succeeded"] += 1

            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "file": file_path,
                    "error": str(e)
                })
                logger.error(f"批量操作失败 {file_path}: {e}")

        logger.info(f"批量操作完成: 成功 {results['succeeded']}, 失败 {results['failed']}")
        return results


class AdvancedFileOperations(SafeFileOperations):
    """高级文件操作类，包含更多复杂功能"""

    @staticmethod
    @retry_on_error(max_retries=3, exceptions=(IOError, OSError))
    def read_file_with_encoding_detection(file_path: str) -> str:
        """
        自动检测编码并读取文件

        Args:
            file_path: 文件路径

        Returns:
            文件内容

        Raises:
            FileProcessingError: 文件读取失败
        """
        try:
            import chardet

            validated_path = validate_file_path(file_path, check_exists=True)
            path_obj = Path(validated_path)

            # 读取文件的一部分来检测编码
            with open(validated_path, 'rb') as f:
                raw_data = f.read(10240)  # 读取前10KB
                encoding_result = chardet.detect(raw_data)
                detected_encoding = encoding_result.get('encoding', 'utf-8')
                confidence = encoding_result.get('confidence', 0)

            logger.debug(f"检测到文件编码: {detected_encoding} (置信度: {confidence:.2f})")

            # 如果置信度太低，使用UTF-8作为默认编码
            if confidence < 0.7:
                detected_encoding = 'utf-8'
                logger.warning(f"编码检测置信度较低，使用UTF-8作为默认编码")

            # 使用检测到的编码读取文件
            with open(validated_path, 'r', encoding=detected_encoding) as f:
                content = f.read()

            logger.info(f"成功读取文件: {file_path}, 编码: {detected_encoding}")
            return content

        except ImportError:
            logger.warning("chardet包未安装，使用UTF-8编码")
            return SafeFileOperations.read_text_file(file_path, encoding='utf-8')
        except Exception as e:
            raise FileProcessingError(f"自动编码检测读取失败: {e}", "ENCODING_DETECTION_ERROR")

    @staticmethod
    def read_file_in_chunks(file_path: str, chunk_size: int = 8192, mode: str = 'r') -> List[str]:
        """
        分块读取大文件

        Args:
            file_path: 文件路径
            chunk_size: 块大小（字节）
            mode: 读取模式

        Returns:
            文件内容块列表
        """
        try:
            validated_path = validate_file_path(file_path, check_exists=True)
            chunks = []

            with open(validated_path, mode, encoding='utf-8') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    chunks.append(chunk)

            logger.info(f"分块读取完成: {file_path}, 共{len(chunks)}块")
            return chunks

        except Exception as e:
            raise FileProcessingError(f"分块读取失败: {e}", "CHUNK_READ_ERROR")

    @staticmethod
    @contextmanager
    def atomic_write(file_path: str, mode: str = 'w', encoding: str = 'utf-8'):
        """
        原子性写入上下文管理器

        Args:
            file_path: 目标文件路径
            mode: 写入模式
            encoding: 编码格式

        Yields:
            临时文件对象
        """
        validated_path = validate_file_path(file_path, check_exists=False)
        path_obj = Path(validated_path)

        # 确保目录存在
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        # 创建临时文件
        temp_file = None
        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode=mode,
                encoding=encoding if 'b' not in mode else None,
                dir=path_obj.parent,
                delete=False,
                prefix=f"{path_obj.stem}_temp_",
                suffix=path_obj.suffix
            ) as temp_file:
                temp_path = temp_file.name
                yield temp_file

            # 原子性移动到目标位置
            shutil.move(temp_path, validated_path)
            logger.info(f"原子性写入完成: {file_path}")

        except Exception as e:
            # 清理临时文件
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            raise FileProcessingError(f"原子性写入失败: {e}", "ATOMIC_WRITE_ERROR")

    @staticmethod
    def create_backup(file_path: str, backup_dir: Optional[str] = None, max_backups: int = 5) -> str:
        """
        创建文件备份

        Args:
            file_path: 原文件路径
            backup_dir: 备份目录，默认为原文件目录下的backups子目录
            max_backups: 最大备份数量

        Returns:
            备份文件路径
        """
        try:
            validated_path = validate_file_path(file_path, check_exists=True)
            path_obj = Path(validated_path)

            # 确定备份目录
            if backup_dir:
                backup_path = Path(backup_dir)
            else:
                backup_path = path_obj.parent / "backups"

            backup_path.mkdir(parents=True, exist_ok=True)

            # 生成备份文件名
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_name = f"{path_obj.stem}_{timestamp}{path_obj.suffix}"
            backup_file_path = backup_path / backup_name

            # 复制文件
            shutil.copy2(validated_path, backup_file_path)

            # 清理旧备份
            AdvancedFileOperations._cleanup_old_backups(backup_path, path_obj.name, max_backups)

            logger.info(f"创建备份成功: {backup_file_path}")
            return str(backup_file_path)

        except Exception as e:
            raise FileProcessingError(f"创建备份失败: {e}", "BACKUP_CREATE_ERROR")

    @staticmethod
    def _cleanup_old_backups(backup_dir: Path, original_name: str, max_backups: int):
        """清理旧备份文件"""
        try:
            # 获取所有相关备份文件
            stem = Path(original_name).stem
            backup_files = []

            for file in backup_dir.glob(f"{stem}_*"):
                if file.is_file():
                    backup_files.append(file)

            # 按修改时间排序，保留最新的
            backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

            # 删除多余的备份
            for old_backup in backup_files[max_backups:]:
                old_backup.unlink()
                logger.debug(f"删除旧备份: {old_backup}")

        except Exception as e:
            logger.warning(f"清理旧备份时出错: {e}")

    @staticmethod
    def secure_delete(file_path: str, passes: int = 3) -> bool:
        """
        安全删除文件（多次覆写）

        Args:
            file_path: 文件路径
            passes: 覆写次数

        Returns:
            是否成功删除
        """
        try:
            validated_path = validate_file_path(file_path, check_exists=True)
            path_obj = Path(validated_path)

            if not path_obj.is_file():
                raise FileProcessingError("只能安全删除文件，不能删除目录", "NOT_A_FILE")

            file_size = path_obj.stat().st_size

            # 多次覆写文件内容
            with open(validated_path, 'r+b') as f:
                for pass_num in range(passes):
                    f.seek(0)
                    # 使用随机数据覆写
                    import secrets
                    random_data = secrets.token_bytes(file_size)
                    f.write(random_data)
                    f.flush()
                    os.fsync(f.fileno())  # 强制写入磁盘

            # 最后删除文件
            path_obj.unlink()
            logger.info(f"安全删除完成: {file_path}")
            return True

        except Exception as e:
            logger.error(f"安全删除失败: {e}")
            return False

    @staticmethod
    def monitor_file_changes(file_path: str, callback, check_interval: float = 1.0):
        """
        监控文件变化

        Args:
            file_path: 文件路径
            callback: 变化时的回调函数
            check_interval: 检查间隔（秒）
        """
        try:
            validated_path = validate_file_path(file_path, check_exists=True)
            path_obj = Path(validated_path)

            last_modified = path_obj.stat().st_mtime
            logger.info(f"开始监控文件变化: {file_path}")

            while True:
                try:
                    current_modified = path_obj.stat().st_mtime
                    if current_modified != last_modified:
                        logger.info(f"检测到文件变化: {file_path}")
                        callback(file_path, last_modified, current_modified)
                        last_modified = current_modified

                    time.sleep(check_interval)

                except KeyboardInterrupt:
                    logger.info("文件监控已停止")
                    break
                except Exception as e:
                    logger.error(f"监控文件时出错: {e}")
                    time.sleep(check_interval)

        except Exception as e:
            raise FileProcessingError(f"启动文件监控失败: {e}", "FILE_MONITOR_ERROR")


class FileSystemHelper:
    """文件系统辅助工具类"""

    @staticmethod
    def get_directory_size(path: str) -> int:
        """
        获取目录总大小

        Args:
            path: 目录路径

        Returns:
            目录大小（字节）
        """
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(file_path)
                    except (OSError, IOError):
                        continue
        except Exception as e:
            logger.error(f"计算目录大小失败: {e}")

        return total_size

    @staticmethod
    def format_file_size(size_bytes: int) -> str:
        """
        格式化文件大小显示

        Args:
            size_bytes: 文件大小（字节）

        Returns:
            格式化的大小字符串
        """
        if size_bytes == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB", "TB"]
        import math
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)

        return f"{s} {size_names[i]}"

    @staticmethod
    def find_files_by_pattern(directory: str, pattern: str, recursive: bool = True) -> List[str]:
        """
        按模式查找文件

        Args:
            directory: 搜索目录
            pattern: 文件名模式（支持通配符）
            recursive: 是否递归搜索

        Returns:
            匹配的文件路径列表
        """
        import fnmatch

        matched_files = []
        try:
            if recursive:
                for root, dirs, files in os.walk(directory):
                    for filename in files:
                        if fnmatch.fnmatch(filename, pattern):
                            matched_files.append(os.path.join(root, filename))
            else:
                for filename in os.listdir(directory):
                    if fnmatch.fnmatch(filename, pattern) and os.path.isfile(os.path.join(directory, filename)):
                        matched_files.append(os.path.join(directory, filename))

        except Exception as e:
            logger.error(f"文件模式搜索失败: {e}")

        return matched_files

    @staticmethod
    def cleanup_empty_directories(root_path: str) -> int:
        """
        清理空目录

        Args:
            root_path: 根目录路径

        Returns:
            删除的空目录数量
        """
        deleted_count = 0
        try:
            for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
                # 跳过根目录
                if dirpath == root_path:
                    continue

                try:
                    # 如果目录为空，删除它
                    if not dirnames and not filenames:
                        os.rmdir(dirpath)
                        deleted_count += 1
                        logger.debug(f"删除空目录: {dirpath}")
                except OSError:
                    continue

        except Exception as e:
            logger.error(f"清理空目录失败: {e}")

        logger.info(f"清理完成，删除了 {deleted_count} 个空目录")
        return deleted_count


# 导出所有类和函数
__all__ = [
    'SafeFileOperations',
    'BatchFileOperations',
    'AdvancedFileOperations',
    'FileSystemHelper'
]