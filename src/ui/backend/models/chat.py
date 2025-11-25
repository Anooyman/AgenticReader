"""聊天相关数据模型"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """聊天消息模型"""
    message: str = Field(..., description="消息内容")


class ChatHistory(BaseModel):
    """聊天历史项模型"""
    role: str = Field(..., description="角色")
    content: str = Field(..., description="内容")
    timestamp: str = Field(..., description="时间戳")


class ChatResponse(BaseModel):
    """聊天响应模型"""
    type: str = Field(..., description="消息类型")
    content: str = Field(..., description="消息内容")
    timestamp: str = Field(..., description="时间戳")


class WebSocketMessage(BaseModel):
    """WebSocket消息模型"""
    type: str = Field(..., description="消息类型")
    content: str = Field(..., description="消息内容")
    timestamp: Optional[str] = Field(None, description="时间戳")


class ChatHistoryResponse(BaseModel):
    """聊天历史响应模型"""
    history: List[List[str]] = Field(..., description="聊天历史")


class WebUrlRequest(BaseModel):
    """Web URL处理请求模型"""
    url: str = Field(..., description="URL地址")
    save_outputs: bool = Field(True, description="是否保存输出")


class ProviderConfig(BaseModel):
    """提供商配置模型"""
    provider: str = Field(..., description="提供商名称")
    pdf_preset: Optional[str] = Field(None, description="PDF预设")