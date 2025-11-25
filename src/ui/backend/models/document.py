"""文档数据模型"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class DocumentModel(BaseModel):
    """文档模型"""
    name: str = Field(..., description="文档名称")
    doc_type: str = Field(..., description="文档类型 (pdf/web)")
    file_path: Optional[str] = Field(None, description="文件路径")
    url: Optional[str] = Field(None, description="URL地址")
    provider: str = Field("openai", description="处理提供商")
    status: str = Field("pending", description="处理状态")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    processed_at: Optional[datetime] = Field(None, description="处理完成时间")

    class Config:
        json_encoders = {
            datetime: lambda dt: dt.isoformat()
        }


class DocumentCreate(BaseModel):
    """创建文档请求模型"""
    name: str
    doc_type: str
    file_path: Optional[str] = None
    url: Optional[str] = None
    provider: str = "openai"


class DocumentSummary(BaseModel):
    """文档总结模型"""
    doc_name: str
    summary_type: str = Field(..., description="总结类型 (brief/detail)")
    content: str
    status: str = "success"


class PDFPageContent(BaseModel):
    """PDF页面内容模型"""
    page: int
    content: str


class PDFContent(BaseModel):
    """PDF内容模型"""
    doc_name: str
    pages: List[PDFPageContent]
    status: str = "success"


class PDFImage(BaseModel):
    """PDF图片模型"""
    page: int
    url: str
    filename: str


class PDFImageList(BaseModel):
    """PDF图片列表模型"""
    doc_name: str
    images: List[PDFImage]
    status: str = "success"