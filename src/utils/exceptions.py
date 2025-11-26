"""
自定义异常类定义

提供项目专用的异常类型，用于更精确的错误处理和调试
"""
from typing import Optional, Any


class LLMReaderBaseException(Exception):
    """LLMReader项目基础异常类"""

    def __init__(self, message: str, error_code: Optional[str] = None, details: Optional[Any] = None):
        """
        初始化基础异常

        Args:
            message (str): 错误消息
            error_code (Optional[str]): 错误代码
            details (Optional[Any]): 详细错误信息
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class ConfigurationError(LLMReaderBaseException):
    """配置相关错误"""
    pass


class FileProcessingError(LLMReaderBaseException):
    """文件处理相关错误"""
    pass


class PDFProcessingError(FileProcessingError):
    """PDF处理相关错误"""
    pass


class LLMServiceError(LLMReaderBaseException):
    """LLM服务相关错误"""
    pass


class VectorDBError(LLMReaderBaseException):
    """向量数据库相关错误"""
    pass


class MemoryManagementError(LLMReaderBaseException):
    """内存管理相关错误"""
    pass


class ValidationError(LLMReaderBaseException):
    """数据验证相关错误"""
    pass


class JSONParsingError(LLMReaderBaseException):
    """JSON解析相关错误"""
    pass


class NetworkError(LLMReaderBaseException):
    """网络请求相关错误"""
    pass


class AuthenticationError(LLMReaderBaseException):
    """认证相关错误"""
    pass