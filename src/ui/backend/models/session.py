"""会话数据模型"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """聊天消息模型"""
    role: str = Field(..., description="消息角色 (user/assistant)")
    content: str = Field(..., description="消息内容")
    timestamp: str = Field(..., description="时间戳")


class SessionModel(BaseModel):
    """会话模型"""
    chat_id: str = Field(..., description="会话ID")
    doc_name: Optional[str] = Field(None, description="文档名称")
    has_pdf_reader: bool = Field(False, description="是否有PDF阅读器")
    has_web_reader: bool = Field(False, description="是否有Web阅读器")
    provider: str = Field("openai", description="LLM提供商")
    messages: List[ChatMessage] = Field(default_factory=list, description="消息列表")
    timestamp: float = Field(..., description="会话时间戳（毫秒）")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }

    def is_meaningful(self) -> bool:
        """判断会话是否有意义"""
        # 必须有文档
        if not self.doc_name:
            return False

        # 必须有消息
        if not self.messages:
            return False

        # 检查是否有实质性对话
        user_messages = [msg for msg in self.messages
                        if msg.role == 'user' and len(msg.content.strip()) >= 3]
        ai_messages = [msg for msg in self.messages
                      if msg.role == 'assistant' and len(msg.content.strip()) >= 10]

        return len(user_messages) > 0 and len(ai_messages) > 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "chatId": self.chat_id,
            "docName": self.doc_name,
            "hasPdfReader": self.has_pdf_reader,
            "hasWebReader": self.has_web_reader,
            "provider": self.provider,
            "messages": [[msg.role, msg.content, msg.timestamp] for msg in self.messages],
            "timestamp": self.timestamp,
            "session_id": self.chat_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


class SessionCreate(BaseModel):
    """创建会话请求模型"""
    doc_name: Optional[str] = None
    provider: str = "openai"
    has_pdf_reader: bool = False
    has_web_reader: bool = False


class SessionUpdate(BaseModel):
    """更新会话请求模型"""
    doc_name: Optional[str] = None
    provider: Optional[str] = None
    has_pdf_reader: Optional[bool] = None
    has_web_reader: Optional[bool] = None
    messages: Optional[List[ChatMessage]] = None


class SessionListResponse(BaseModel):
    """会话列表响应模型"""
    sessions: Dict[str, Dict[str, Any]]
    count: int
    status: str = "success"


class SessionExportRequest(BaseModel):
    """会话导出请求模型"""
    filename: Optional[str] = None


class SessionImportRequest(BaseModel):
    """会话导入请求模型"""
    merge: bool = True