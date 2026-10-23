"""
LLMReader 项目常量配置
常量定义文件，用于集中管理项目中的各种配置常量，避免硬编码魔术数字
"""

import os
from pathlib import Path
from typing import List, Optional

# === 处理限制常量 ===
class ProcessingLimits:
    """处理过程中的各种限制常量"""

    # Retrieval Agent 迭代次数配置
    MAX_RETRIEVAL_ITERATIONS = 10  # Retrieval Agent 最大迭代次数（ReAct循环）

    # Retrieval Agent 持久化历史长度控制
    MAX_PERSISTENT_HISTORY_LENGTH = 10  # 持久化历史的最大长度（thoughts, actions, observations, retrieved_content）
    # 只保留最近的 N 条记录，避免上下文无限增长
    # 建议值：5-20，根据 LLM 上下文窗口大小调整

    # 注意：会话历史相关配置（max_messages, max_tokens）已移至 SessionHistoryConfig


# === 检索去重窗口配置 ===
class RetrievalDedupConfig:
    """检索去重窗口配置

    去重记录以「文档哈希 -> 最近命中的对话轮次」的形式保存，
    只保留最近 N 轮对话的命中记录，更早的记录自动丢弃。
    这样对话再久，检索空间也不会因去重集合无限增长而单调收窄；
    需要早期内容时应通过「关键信息摘要 + 再次检索」获得，
    而不是依赖去重集合永久记住所有已检索文档。

    可通过环境变量 RETRIEVAL_DEDUP_WINDOW 覆盖（非法值回退默认 5）。
    """

    DEFAULT_WINDOW = 5

    try:
        WINDOW = int(os.environ.get("RETRIEVAL_DEDUP_WINDOW", DEFAULT_WINDOW))
    except (TypeError, ValueError):
        WINDOW = DEFAULT_WINDOW


# === 文件和路径常量 ===
class PathConstants:
    """文件路径相关常量"""

    # 数据目录结构
    DATA_ROOT = "data"
    PDF_DIR = "pdf"
    PDF_IMAGE_DIR = "pdf_image"
    JSON_DATA_DIR = "json_data"
    VECTOR_DB_DIR = "vector_db"
    OUTPUT_DIR = "output"
    SEARCH_CACHE_DIR = "search_cache"  # SearchAgent 搜索结果缓存
    WEB_CONTENT_DIR = "web_content"  # Use Case 2 URL 内容原始文件

    # 派生产物的命名约定（全仓库唯一出处，禁止在调用点手抄字面量）
    VECTOR_DB_SUFFIX = "_data_index"      # data/vector_db/{doc_name}_data_index/
    BRIEF_SUMMARY_SUFFIX = "_brief_summary"  # data/output/{doc_name}_brief_summary.md
    # 历史遗留的摘要命名（数据管理页删除/统计时一并覆盖，顺序即优先级）
    SUMMARY_SUFFIXES = ("_brief_summary", "_summary", "")
    SUMMARY_EXTENSIONS = (".md", ".pdf")


# ==================== 派生数据路径 helper ====================
#
# 这些 helper 是「向量库目录 / 摘要文件」路径的唯一生成入口。
# 历史上 7-8 处调用点各自手抄 f"{doc}_data_index" 字面量，抄漏后缀就产生
# 删不掉的孤儿 FAISS 目录（UI 删除端点、rebuild 清理旧索引都踩过）。
# 任何新增调用点一律走这里，不要再拼字符串。

def get_data_root() -> Path:
    """
    数据根目录（PathConstants.DATA_ROOT 的 Path 形式）。

    配置值允许是相对路径；相对时锚定到项目根，使路径与进程 cwd 无关——
    UI 由 run_server / uvicorn 从任意目录启动时，读写路径仍然一致。
    """
    root = Path(PathConstants.DATA_ROOT)
    if root.is_absolute():
        return root
    return Path(__file__).resolve().parents[2] / root


def get_vector_db_dir() -> Path:
    """向量库根目录：{data_root}/vector_db"""
    return get_data_root() / PathConstants.VECTOR_DB_DIR


def get_vector_db_path(doc_name: str) -> Path:
    """
    单个文档的 FAISS 向量库目录：{data_root}/vector_db/{doc_name}_data_index

    Args:
        doc_name: 文档名（不含扩展名，调用方自行去掉 .pdf）

    Returns:
        向量库目录 Path（不保证存在）
    """
    return get_vector_db_dir() / f"{doc_name}{PathConstants.VECTOR_DB_SUFFIX}"


def get_metadata_db_path() -> Path:
    """元数据向量库目录：{data_root}/vector_db/_metadata"""
    return get_vector_db_dir() / "_metadata"


def get_output_dir(doc_name: Optional[str] = None) -> Path:
    """
    摘要/报告输出目录。

    Args:
        doc_name: 为 None 时返回输出根目录 {data_root}/output；
            传入文档名时返回历史遗留的按文档分目录 {data_root}/output/{doc_name}
            （当前索引流程不再写这个目录，rebuild 清理时仍需照顾旧产物）

    Returns:
        输出目录 Path（不保证存在）
    """
    base = get_data_root() / PathConstants.OUTPUT_DIR
    return base if doc_name is None else base / doc_name


def get_brief_summary_path(doc_name: str) -> Path:
    """
    单个文档的简要摘要文件：{data_root}/output/{doc_name}_brief_summary.md

    与 IndexingAgent.generate_brief_summary 的落盘位置、以及数据管理页
    （data.py delete_document_parts）统计/删除的摘要路径保持一致。
    """
    return get_output_dir() / f"{doc_name}{PathConstants.BRIEF_SUMMARY_SUFFIX}.md"


def get_summary_paths(doc_name: str) -> List[Path]:
    """
    单个文档所有可能的摘要文件（含历史命名），顺序与数据管理页一致：
    后缀 _brief_summary / _summary / 无后缀 × 扩展名 .md / .pdf
    """
    return [
        get_output_dir() / f"{doc_name}{suffix}{ext}"
        for suffix in PathConstants.SUMMARY_SUFFIXES
        for ext in PathConstants.SUMMARY_EXTENSIONS
    ]


# === PDF处理常量 ===
class PDFConstants:
    """PDF处理相关常量"""

    # PDF转图片质量配置
    DEFAULT_DPI = 300
    QUALITY_LEVELS = {
        "low": {"dpi": 150, "scale": 2.0},
        "medium": {"dpi": 200, "scale": 3.0},
        "high": {"dpi": 300, "scale": 4.0},
        "ultra": {"dpi": 600, "scale": 5.0}
    }

    # 支持的图片格式
    SUPPORTED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.bmp', '.gif']


# === LLM相关常量 ===
class LLMConstants:
    """LLM处理相关常量"""

    # 默认配置
    DEFAULT_ENCODING = "o200k_base"


# === 会话历史管理常量 ===
class SessionHistoryConfig:
    """会话历史管理配置

    定义不同类型会话的消息历史管理参数。
    每种会话类型包含以下配置：
    - max_messages: 最大消息数量（兜底值，当LLM总结失败时使用）
    - max_tokens: 最大Token数量限制（超过则触发截断）
    - summary_threshold: 触发LLM总结的对话轮数阈值
    - use_llm_summary: 是否启用LLM智能总结（默认True）

    Note:
        - 对话轮数 = 消息数量 / 2（一轮对话包含1个问题和1个回答）
        - summary_threshold=3 表示第4轮对话时触发总结（即超过3轮）
        - max_messages 应设置为远大于 summary_threshold*2 的值，作为总结失败的兜底
        - max_tokens 用于控制总Token数，防止超过LLM上下文窗口限制
    """

    # Web Chat Session 配置（session_id="chat"）
    # 用于 UI 的 Web 内容对话，使用较宽松的限制
    WEB_CHAT = {
        "max_messages": 10,           # 兜底值：总结失败时的硬上限
        "max_tokens": 65536,           # 最大Token数（Claude 3.5 Sonnet上下文窗口）
        "summary_threshold": 10,        # 10轮对话后触发总结（20条消息）
        "use_llm_summary": True,       # 启用LLM智能总结
    }

    # PDF Chat Session 配置（session_id="answer"等）
    # 用于 PDF 文档对话（CLI 和 UI），使用较严格的限制
    PDF_CHAT = {
        "max_messages": 10,            # 兜底值：总结失败时的硬上限
        "max_tokens": 65536,           # 最大Token数（Claude 3.5 Sonnet上下文窗口）
        "summary_threshold": 10,        # 10轮对话后触发总结（20条消息）
        "use_llm_summary": True,       # 启用LLM智能总结
    }

    # 默认 Session 配置
    # 用于其他未明确分类的会话
    DEFAULT = {
        "max_messages": 30,            # 兜底值：总结失败时的硬上限
        "max_tokens": 65536,           # 最大Token数（Claude 3.5 Sonnet上下文窗口）
        "summary_threshold": 10,        # 10轮对话后触发总结（20条消息）
        "use_llm_summary": True,       # 启用LLM智能总结
    }

    # Session ID 到配置的映射
    SESSION_TYPE_MAP = {
        "chat": WEB_CHAT,              # Web Chat UI
        "answer": PDF_CHAT,            # PDF Chat (UI & CLI)
    }

    @classmethod
    def get_config(cls, session_id: str) -> dict:
        """
        根据 session_id 获取对应的配置

        Args:
            session_id: 会话ID

        Returns:
            配置字典，包含 max_messages, summary_threshold, use_llm_summary
        """
        return cls.SESSION_TYPE_MAP.get(session_id, cls.DEFAULT)


# === Reader处理常量 ===
class ReaderConstants:
    """Reader相关常量"""

    # 分块处理
    DEFAULT_CHUNK_COUNT = 20  # PDF分块处理的默认大小


# === 安全相关常量 ===
class SecurityConstants:
    """安全验证相关常量"""

    # 文件大小限制
    MAX_FILE_SIZE_MB = 100  # 文件最大大小（MB）

    # URL长度限制
    MAX_URL_LENGTH = 2048  # URL最大长度

    # 输入长度限制
    MAX_INPUT_LENGTH = 10000  # 一般输入的最大长度

    # 支持的文件扩展名
    ALLOWED_EXTENSIONS = {
        '.pdf', '.txt', '.md', '.json', '.csv',
        '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx',
        '.jpg', '.jpeg', '.png', '.gif', '.bmp',
        '.mp3', '.mp4', '.wav', '.avi'
    }