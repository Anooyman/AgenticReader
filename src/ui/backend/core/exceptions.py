"""自定义异常类"""

from typing import Any, Dict, Optional


class AppException(Exception):
    """应用基础异常类"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class SessionNotFoundError(AppException):
    """会话未找到异常"""

    def __init__(self, session_id: str):
        super().__init__(
            message=f"Session not found: {session_id}",
            error_code="SESSION_NOT_FOUND",
            details={"session_id": session_id}
        )


class DocumentNotFoundError(AppException):
    """文档未找到异常"""

    def __init__(self, doc_name: str):
        super().__init__(
            message=f"Document not found: {doc_name}",
            error_code="DOCUMENT_NOT_FOUND",
            details={"doc_name": doc_name}
        )


class ValidationError(AppException):
    """数据验证异常"""

    def __init__(self, field: str, value: Any, reason: str):
        super().__init__(
            message=f"Validation failed for field '{field}': {reason}",
            error_code="VALIDATION_ERROR",
            details={"field": field, "value": value, "reason": reason}
        )


class ConfigurationError(AppException):
    """配置错误异常"""

    def __init__(self, config_key: str, reason: str):
        super().__init__(
            message=f"Configuration error for '{config_key}': {reason}",
            error_code="CONFIGURATION_ERROR",
            details={"config_key": config_key, "reason": reason}
        )


class ServiceError(AppException):
    """服务层异常"""

    def __init__(self, service: str, operation: str, reason: str):
        super().__init__(
            message=f"Service error in {service}.{operation}: {reason}",
            error_code="SERVICE_ERROR",
            details={"service": service, "operation": operation, "reason": reason}
        )


class PDFNotFoundError(AppException):
    """PDF文件未找到异常"""

    def __init__(self, pdf_name: str):
        super().__init__(
            message=f"PDF not found: {pdf_name}",
            error_code="PDF_NOT_FOUND",
            details={"pdf_name": pdf_name}
        )


class PDFProcessingError(AppException):
    """PDF处理异常"""

    def __init__(self, pdf_name: str, reason: str):
        super().__init__(
            message=f"PDF processing failed for '{pdf_name}': {reason}",
            error_code="PDF_PROCESSING_ERROR",
            details={"pdf_name": pdf_name, "reason": reason}
        )