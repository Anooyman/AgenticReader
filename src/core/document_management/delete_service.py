"""文档删除的唯一权威实现（REFACTOR_REPORT P2-1 后半）。

历史上「删掉一个文档及其全部派生产物」这件事有三份平行实现：

- ``manager.delete_document_files()``（CLI 路）
- ``documents.delete_document``（UI 单文档删）
- ``data.delete_document_parts``（数据管理页，可按 parts 选择）

三份各自删的东西不一样（谁删 registry、谁删 brief、谁查 metadata 的 index.faiss、
谁做 safe_path 校验都不统一）。D3 的教训是同一类问题：清理逻辑一旦分叉，
某一路漏删就留下孤儿产物。本模块把删除收敛为**唯一实现**，语义取三份的**并集**：
凡任意一路以前删过的东西，收敛后所有路都删。

调用方（都只做"翻译层"，不再自己拼路径 / rmtree）：
- CLI ``manager.delete_document_files()``：保留列清单 + ``input()`` 确认的交互包装，
  真正的清理委托 ``delete_document_service()``。
- ``documents.delete_document`` / ``data.delete_document_parts``：只做 parts 映射、
  标签文案与 HTTP 状态码/响应体的翻译。

与仓库既有范式保持一致的几点：
- 函数无交互、无 ``print()``、不抛 ``HTTPException``，返回结构化结果
  （``DeleteDocumentResult``），由调用方决定展示与错误语义——与
  ``queue_store``/``registry`` 那套"纯数据进、纯数据出"的服务层一致。
- registry 的写一律走 ``DocumentRegistry.delete()``，即锁内重读-改-写 +
  ``src.utils.json_io.write_json_atomic`` 原子落盘；本模块绝不自己
  ``open('w')`` 写 ``doc_registry.json``。
- 所有按 doc_name 拼出来的路径都过 ``src.utils.path_guard.safe_path()``；
  注册表里记录的绝对路径（``generated_files`` / ``doc_path``）也要先断言落在
  数据目录内才允许删除，防止被污染的记录把 rmtree 引到数据目录之外。
- 删掉向量库目录后显式调用
  ``src.core.vector_db.vector_db_client.invalidate_vector_db_cache(path)``
  作废读侧的进程级索引缓存（与波次5-B 的缓存协同）；
  ``MetadataVectorDB`` 内部的 rmtree 已自带失效，本模块不重复依赖它。

部件（parts）词汇表：
    json_data  data/json_data/{doc}/            解析/分块/章节 JSON
    vector_db  data/vector_db/{doc}_data_index/ FAISS 索引目录（= 索引目录）
    images     data/pdf_image/{doc}/            PDF 页面图
    summary    data/output/{doc}{后缀}{.md,.pdf} 摘要产物（历史命名全覆盖）
    brief      data/output/{doc}_brief_summary.md 简版摘要（索引落盘的唯一命名）
    generated  registry.generated_files 里登记的产物路径
    registry   doc_registry.json 里的记录（连带 MetadataVectorDB 的元数据向量）
    source_pdf data/pdf/{doc}.pdf 或注册表 doc_path（**只能显式指定**，
               "all" 与 None 都不含它——与数据管理页既有语义一致）

``parts=None`` 表示全删（= ALL_PARTS，不含 source_pdf）。
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from src.config.constants import (
    PathConstants,
    get_brief_summary_path,
    get_data_root,
    get_metadata_db_path,
    get_summary_paths,
    get_vector_db_path,
)
from src.core.document_management import DocumentRegistry
from src.utils.path_guard import normalize_doc_name, safe_path

logger = logging.getLogger(__name__)

# ==================== 部件词汇表 ====================

PART_JSON_DATA = "json_data"
PART_VECTOR_DB = "vector_db"
PART_IMAGES = "images"
PART_SUMMARY = "summary"
PART_BRIEF = "brief"
PART_GENERATED = "generated"
PART_REGISTRY = "registry"
PART_SOURCE_PDF = "source_pdf"
PART_METADATA_DB = "metadata_db"  # 内部件名：随 registry 一起清，不对外暴露

#: 全删（parts=None）时展开的部件集合。刻意**不**含 source_pdf：
#: 上传的原始 PDF 属于用户资产，必须显式点名才删（数据管理页既有语义）。
ALL_PARTS: Tuple[str, ...] = (
    PART_JSON_DATA,
    PART_VECTOR_DB,
    PART_IMAGES,
    PART_SUMMARY,
    PART_BRIEF,
    PART_GENERATED,
    PART_REGISTRY,
)

#: 调用方可以用的别名——UI 侧三份实现的叫法本来就不同（"json" vs "json_data"、
#: "images" vs "pdf_image"），收敛后由这里统一翻译，前端零改动。
_ALIASES: Dict[str, str] = {
    "json": PART_JSON_DATA,
    "json_data": PART_JSON_DATA,
    "json_folder": PART_JSON_DATA,
    "vector_db": PART_VECTOR_DB,
    "vector": PART_VECTOR_DB,
    "vector_database": PART_VECTOR_DB,
    "faiss": PART_VECTOR_DB,
    "index": PART_VECTOR_DB,
    "images": PART_IMAGES,
    "image": PART_IMAGES,
    "pdf_image": PART_IMAGES,
    "summary": PART_SUMMARY,
    "summaries": PART_SUMMARY,
    "output": PART_SUMMARY,
    "brief": PART_BRIEF,
    "brief_summary": PART_BRIEF,
    "generated": PART_GENERATED,
    "generated_files": PART_GENERATED,
    "registry": PART_REGISTRY,
    "register": PART_REGISTRY,
    "pdf": PART_SOURCE_PDF,
    "source_pdf": PART_SOURCE_PDF,
    "source": PART_SOURCE_PDF,
}

#: "四件套齐全"即视为完全删除（数据管理页既有规则，保留为所有入口的共同语义）
_FULL_DELETE_SET = frozenset({PART_JSON_DATA, PART_VECTOR_DB, PART_IMAGES, PART_SUMMARY})


def normalize_parts(parts: Optional[Iterable[str]]) -> Set[str]:
    """把调用方给的部件名（含别名 / "all" / 大小写差异）翻译成规范集合。

    Args:
        parts: 部件名序列；``None`` 表示全删（展开为 :data:`ALL_PARTS`）。
            未知名字被忽略——与数据管理页既有行为一致（不认识的部件不删东西，
            也不报错）。

    Returns:
        Set[str]: 规范部件名集合（可能包含 ``source_pdf``）。
    """
    if parts is None:
        return set(ALL_PARTS)

    requested: Set[str] = set()
    for raw in parts:
        name = str(raw).strip().lower()
        if not name:
            continue
        if name == "all":
            # "all" 展开为全删部件，但同样不含源 PDF（既有语义）
            requested.update(ALL_PARTS)
            continue
        canonical = _ALIASES.get(name)
        if canonical is None:
            logger.debug("[delete_service] 忽略未知部件: %s", raw)
            continue
        requested.add(canonical)
    return requested


# ==================== 结果对象 ====================


@dataclass
class DeleteItem:
    """一次删除动作的产物记录（成功或失败各一条）。"""

    part: str
    """规范部件名，如 ``json_data`` / ``brief`` / ``metadata_db``。"""

    path: Optional[str] = None
    """被删（或尝试删）的路径；registry / metadata 这类非文件项为 None。"""

    size_mb: float = 0.0
    """释放的 MB（文件 + 目录内文件递归求和）。"""

    detail: Optional[str] = None
    """附加信息，例如摘要文件的后缀 ``".md"``。"""

    error: Optional[str] = None
    """失败原因；为 None 表示这条是成功记录。"""

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class DeleteDocumentResult:
    """``delete_document_service()`` 的结构化返回值。"""

    doc_name: str
    """调用方传入的原始文档名。"""

    doc_name_base: str
    """去掉 ``.pdf`` 后缀后的名字（路径拼装实际用的名字）。"""

    doc_id: Optional[str] = None
    """注册表里查到的 doc_id；无记录时为 None。"""

    doc_info: Optional[Dict[str, Any]] = None
    """注册表记录快照。"""

    requested_parts: Tuple[str, ...] = ()
    """规范化后的部件集合（排序后，便于日志与断言）。"""

    deleted: List[DeleteItem] = field(default_factory=list)
    failed: List[DeleteItem] = field(default_factory=list)

    registry_removed: bool = False
    """是否成功从 doc_registry.json 注销了记录。"""

    @property
    def freed_space_mb(self) -> float:
        """释放的总空间（MB，未取整——取整由调用方按各自的响应格式做）。"""
        return sum(item.size_mb for item in self.deleted)

    @property
    def deleted_parts(self) -> Set[str]:
        return {item.part for item in self.deleted}

    @property
    def anything_done(self) -> bool:
        """是否真的删掉了 / 注销了点什么（三路上层都据此判定 404）。"""
        return bool(self.deleted) or self.registry_removed

    @property
    def success(self) -> bool:
        """无失败且确实做了清理——CLI 路据此返回 bool。"""
        return self.anything_done and not self.failed


# ==================== 路径拼装（唯一权威处） ====================


@dataclass(frozen=True)
class DocumentPaths:
    """一个文档的全部派生产物路径（按数据目录根 + 规范名拼装，全部过 safe_path）。"""

    doc_name_base: str
    json_data: Path
    vector_db: Path
    images: Path
    brief: Path
    summaries: Tuple[Path, ...]
    source_pdf: Path


def document_paths(doc_name: str) -> DocumentPaths:
    """拼装一个文档的全部派生产物路径（删除与统计共用的**唯一**路径生成处）。

    路径全部经 :func:`src.utils.path_guard.safe_path` 校验，越界即抛
    ``ValueError``；名字先经 :func:`normalize_doc_name` 去掉结尾的 ``.pdf``，
    保证各部件用的是同一个基名（历史上三份实现各自 ``replace('.pdf','')``，
    拼法略有出入）。

    Args:
        doc_name: 文档名（可带 .pdf 后缀）

    Returns:
        DocumentPaths

    Raises:
        ValueError: 名称非法或解析后越出对应数据目录
    """
    base = normalize_doc_name(doc_name)
    if not base:
        raise ValueError(f"非法文档名：{doc_name}")

    # 数据根目录先整体校验一次（与 UI 侧既有 safe_path(DATA_DIR, doc_name) 等价）
    safe_path(get_data_root(), base)

    return DocumentPaths(
        doc_name_base=base,
        json_data=safe_path(get_data_root() / PathConstants.JSON_DATA_DIR, base),
        vector_db=get_vector_db_path(base),
        images=safe_path(get_data_root() / PathConstants.PDF_IMAGE_DIR, base),
        brief=get_brief_summary_path(base),
        summaries=tuple(get_summary_paths(base)),
        # 源 PDF 文件名要带 .pdf 后缀，而 safe_path 会剥掉结尾的 .pdf 再校验，
        # 所以这里校验目录、再自己拼回文件名（与 documents.py 上传处的做法一致）
        source_pdf=safe_path(get_data_root() / PathConstants.PDF_DIR, base).parent
        / f"{base}.pdf",
    )


def _ensure_under_data_root(path: Path) -> Optional[Path]:
    """注册表里记录的路径（generated_files / doc_path）必须落在数据目录内才允许删。

    Returns:
        解析后的绝对路径；越界或解析失败返回 None（调用方据此拒绝删除并记一条失败）。
    """
    data_root = get_data_root().resolve()
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, ValueError) as e:
        logger.warning("[delete_service] 登记路径无法解析，拒绝删除: %s (%s)", path, e)
        return None
    if not resolved.is_relative_to(data_root):
        logger.warning(
            "[delete_service] 登记路径越出数据目录 %s，拒绝删除: %s", data_root, resolved
        )
        return None
    return resolved


def _invalidate_vector_db_cache(path: Path) -> None:
    """删完向量库目录后作废读侧的进程级索引缓存（波次5-B 的 VectorDBClient 缓存）。

    正常情况下 (mtime_ns, size) 指纹会让目录消失后的 key 取不到，但显式失效一次
    才能同时释放内存里那份 FAISS 对象，并保证"同名同尺寸的旧对象"不可能再命中。
    延迟 import：不让 faiss/langchain 进入 core 删除路径的模块级导入链。
    """
    try:
        from src.core.vector_db.vector_db_client import invalidate_vector_db_cache

        invalidate_vector_db_cache(str(path))
    except Exception as e:  # pragma: no cover - 缓存失效失败不应影响删除主流程
        logger.debug("[delete_service] 向量库缓存失效失败（忽略）: %s", e)


def _size_mb(path: Path) -> float:
    """文件/目录大小（MB），递归统计，读不到的条目跳过。"""
    try:
        if not path.exists():
            return 0.0
        if path.is_file():
            return path.stat().st_size / (1024 * 1024)
        total = 0
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except (OSError, PermissionError):
                    continue
        return total / (1024 * 1024)
    except OSError:
        return 0.0


# ==================== 删除主流程 ====================


def delete_document_service(
    doc_name: str,
    *,
    parts: Optional[Iterable[str]] = None,
    delete_source_pdf: bool = False,
    registry: Optional[DocumentRegistry] = None,
) -> DeleteDocumentResult:
    """删除一个文档的派生产物并注销注册表记录（全仓库唯一权威实现）。

    语义是历史上三份实现的**并集**：任意一路以前会清的东西，这里都会清；
    漏删（例如 CLI 路只认 ``_brief_summary.md``、UI 单文档删不碰
    ``generated_files`` 登记的产物）在此一并补齐。

    Args:
        doc_name: 文档名，可带 ``.pdf`` 后缀；非法名（空 / 含路径分隔符 /
            以点开头 / 解析后越出数据目录）抛 ``ValueError``，由调用方翻译成
            各自的错误语义（UI → 400，CLI → 返回 False）。
        parts: 要删除的部件子集，取值见模块 docstring；支持 ``"all"`` 与常见别名
            （``"json"``/``"vector_db"``/``"images"``/``"summary"``/``"pdf"``/...）。
            ``None`` 表示全删（:data:`ALL_PARTS`，不含源 PDF）。
        delete_source_pdf: 是否连 ``data/pdf/{doc}.pdf``（或注册表 ``doc_path``）
            一起删。默认 False——与三份既有实现一致：全删不带源文件，必须显式点名。
        registry: 可注入的注册表实例（测试用）；默认按 ``DATA_ROOT`` 新建。

    Returns:
        DeleteDocumentResult: 结构化结果。本函数**不抛业务异常**——单个产物删不掉
        只进 ``result.failed``，调用方据此决定返回 500、"partial" 还是打印失败项；
        幂等：产物不存在时视为已删，不报错，重复调用安全。

    Note:
        删除顺序固定为「派生产物 → MetadataVectorDB 元数据 → Registry」：
        ``MetadataVectorDB.delete_document()`` 会回读注册表拿 doc_name 打日志，
        所以必须在 registry 注销之前调用（数据管理页既有注释的约定）。
    """
    paths = document_paths(doc_name)
    base = paths.doc_name_base

    requested = normalize_parts(parts)
    if delete_source_pdf:
        requested.add(PART_SOURCE_PDF)

    result = DeleteDocumentResult(
        doc_name=str(doc_name),
        doc_name_base=base,
        requested_parts=tuple(sorted(requested)),
    )

    reg = registry if registry is not None else DocumentRegistry()

    # 注册表记录：先按去后缀名查，再按原名兜底（数据管理页历史上用原始名查过，
    # 万一有记录带着 .pdf 后缀存进去，也能被清理掉——并集语义）。
    # DocumentRegistry 是构造期快照 + 锁内重读-改-写的无状态壳，这里现构造即可。
    doc_info = reg.get_by_name(base) or reg.get_by_name(str(doc_name))
    result.doc_info = doc_info
    result.doc_id = doc_info.get("doc_id") if doc_info else None

    # ---- 1. 派生产物 ----
    if PART_JSON_DATA in requested:
        _remove(result, PART_JSON_DATA, paths.json_data)

    if PART_VECTOR_DB in requested:
        _remove(result, PART_VECTOR_DB, paths.vector_db)

    if PART_IMAGES in requested:
        _remove(result, PART_IMAGES, paths.images)

    # brief 先于 summary：{doc}_brief_summary.md 同时也在 get_summary_paths() 的
    # 历史命名清单里，先按 brief 删掉它，它才能在自己的部件名下记账；
    # 只点名 summary 时（数据管理页既有行为）仍会连带删掉它——并集语义不变。
    if PART_BRIEF in requested and paths.brief.exists():
        _remove(result, PART_BRIEF, paths.brief, detail=paths.brief.suffix)

    if PART_SUMMARY in requested:
        for summary_file in paths.summaries:
            if summary_file.exists():
                _remove(result, PART_SUMMARY, summary_file, detail=summary_file.suffix)

    if PART_GENERATED in requested:
        _delete_generated_files(result, doc_info)

    if PART_SOURCE_PDF in requested:
        _delete_source_pdf(result, paths, doc_info)

    # ---- 2. registry 注销（连带 MetadataVectorDB） ----
    # 既有语义保留：显式点名 registry，或四件套全要（视为完全删除）时注销。
    wants_registry = (PART_REGISTRY in requested) or (
        _FULL_DELETE_SET.issubset(requested)
    )
    if wants_registry and result.doc_id:
        _delete_metadata(result, result.doc_id)
        try:
            if reg.delete(result.doc_id):
                result.registry_removed = True
            else:
                # 记录可能已被并发删除：目标状态（注册表里不再有它）已达成，
                # 与数据管理页既有行为一致，不算失败
                logger.warning("[delete_service] 注册表中已无该记录（可能已被并发删除）: %s", result.doc_id)
                result.registry_removed = True
        except Exception as e:
            logger.error("[delete_service] 注册表注销失败: %s", e)
            result.failed.append(DeleteItem(part=PART_REGISTRY, error=str(e)))

    logger.info(
        "🗑️ 文档删除完成: %s（parts=%s, 删除 %d 项, 失败 %d 项, 注销 registry=%s, 释放 %.2fMB）",
        base,
        list(result.requested_parts),
        len(result.deleted),
        len(result.failed),
        result.registry_removed,
        result.freed_space_mb,
    )
    return result


def _remove(
    result: DeleteDocumentResult,
    part: str,
    path: Path,
    *,
    detail: Optional[str] = None,
) -> None:
    """删除单个文件/目录（幂等：不存在即视为已删），并把结果记进 result。"""
    try:
        if not path.exists():
            return
        # 同一路径不重复记账：约定路径与注册表登记路径常指向同一个目录，
        # 第二次尝试既删不出新东西，也只会把同一份失败原因刷两遍
        already = [item for item in result.deleted + result.failed
                   if item.part == part and item.path == str(path)]
        if already:
            return
        size = _size_mb(path)
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:  # pragma: no cover - 设备文件/断链之类，当删不掉处理
            raise OSError(f"路径既不是文件也不是目录: {path}")
        # 波次5-B 的读侧缓存：删掉目录/索引后必须作废，否则同名路径可能命中旧对象
        _invalidate_vector_db_cache(path)
        result.deleted.append(
            DeleteItem(part=part, path=str(path), size_mb=size, detail=detail)
        )
    except Exception as e:
        logger.error("[delete_service] 删除失败 %s: %s (%s)", part, path, e)
        result.failed.append(
            DeleteItem(part=part, path=str(path), detail=detail, error=str(e))
        )


def _delete_generated_files(result: DeleteDocumentResult, doc_info: Optional[Dict[str, Any]]) -> None:
    """删除注册表 generated_files 里登记的产物（images / json_data / vector_db / summaries）。

    这三份老实现都没做这一步（registry.delete_all_files() 里有等价逻辑但零调用者），
    属于漏删：一旦索引流程写出的产物命名与 constants helper 的约定漂移，
    按约定拼出来的路径就删不到，留下孤儿文件。这里按注册表记录补删一次。
    登记路径来自注册表而非请求，仍一律断言落在数据目录内才动手。
    """
    if not doc_info:
        return
    generated = doc_info.get("generated_files") or {}
    if not isinstance(generated, dict):
        return

    def _remove_recorded(part: str, raw: Any) -> None:
        if not raw:
            return
        candidates: List[Path] = []
        if isinstance(raw, (list, tuple)):
            candidates = [Path(x) for x in raw if x]
        else:
            candidates = [Path(raw)]
        for candidate in candidates:
            resolved = _ensure_under_data_root(candidate)
            if resolved is None:
                result.failed.append(
                    DeleteItem(part=part, path=str(candidate), error="登记路径越出数据目录，已拒绝删除")
                )
                continue
            if not resolved.exists():
                continue
            # 图片登记的是逐个文件，但历史上删除都是整目录删：登记项的父目录
            # 若正好是该文档的图片目录，就整目录删掉，避免留下空壳。
            if part == PART_IMAGES and resolved.is_file():
                _remove(result, part, resolved.parent)
            elif part == PART_JSON_DATA and resolved.is_file():
                _remove(result, part, resolved.parent)
            else:
                _remove(result, part, resolved)

    _remove_recorded(PART_IMAGES, generated.get("images"))
    _remove_recorded(PART_JSON_DATA, generated.get("json_data"))
    _remove_recorded(PART_VECTOR_DB, generated.get("vector_db"))
    _remove_recorded(PART_SUMMARY, generated.get("summaries"))


def find_source_pdf(
    doc_name: str, doc_info: Optional[Dict[str, Any]] = None
) -> Optional[Path]:
    """定位文档的本地源 PDF（删除与统计共用的唯一出处）。

    候选顺序与数据管理页既有实现一致：``data/pdf/{doc}.pdf`` 优先，其次注册表
    记录的 ``doc_path``（可能是索引时的外部路径）。数据管理页的 ``has_pdf`` /
    ``pdf_size_mb`` 与实际被删的文件因此不会各拼一套而漂移。

    Args:
        doc_name: 文档名（可带 .pdf 后缀）
        doc_info: 注册表记录（可选，用于 doc_path 回退）

    Returns:
        存在的源文件路径；非法名或找不到时返回 None
    """
    try:
        paths = document_paths(doc_name)
    except ValueError as e:
        logger.debug("[delete_service] 非法文档名，无法定位源 PDF: %s (%s)", doc_name, e)
        return None

    for candidate in _source_pdf_candidates(paths, doc_info):
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _delete_source_pdf(
    result: DeleteDocumentResult,
    paths: DocumentPaths,
    doc_info: Optional[Dict[str, Any]],
) -> None:
    """删除本地源 PDF（仅当调用方显式点名 parts 含 ``pdf`` / ``source_pdf``）。"""
    target = find_source_pdf(paths.doc_name_base, doc_info)
    if target is not None:
        _remove(result, PART_SOURCE_PDF, target)
    else:
        logger.info("[delete_service] 未找到 %s 的源 PDF 文件，跳过", paths.doc_name_base)


def _source_pdf_candidates(paths: DocumentPaths, doc_info: Optional[Dict[str, Any]]) -> List[Path]:
    """源 PDF 的候选路径（data/pdf/{doc}.pdf → 注册表 doc_path）。

    第二条候选是索引时记录的原始文件，可能位于数据目录之外（数据管理页既有行为，
    删的是注册表自己记录的、用户上传时的那份源文件，不接受请求方拼出来的路径）。
    """
    candidates: List[Path] = [paths.source_pdf]
    if doc_info:
        doc_path = doc_info.get("doc_path")
        if doc_path:
            candidates.append(Path(doc_path))
    return candidates


def _delete_metadata(result: DeleteDocumentResult, doc_id: str) -> None:
    """从 MetadataVectorDB 删除该文档的元数据向量。

    与两份 UI 实现一致：先确认元数据索引文件真的存在，再构造 MetadataVectorDB
    ——否则为了"删"反而把空索引初始化出来（CLI 路以前无条件 new，属副作用）。
    MetadataVectorDB 内部的 rmtree 已自带索引缓存失效，这里不重复处理。
    """
    try:
        metadata_index_file = get_metadata_db_path() / "index.faiss"
        if not metadata_index_file.exists():
            logger.info("[delete_service] 元数据向量库未初始化，跳过删除")
            return

        from src.core.vector_db.metadata_db import MetadataVectorDB  # 延迟 import：不把 faiss 拖进删除路径

        if MetadataVectorDB().delete_document(doc_id):
            result.deleted.append(DeleteItem(part=PART_METADATA_DB))
        else:
            result.failed.append(
                DeleteItem(part=PART_METADATA_DB, error="删除未完全成功")
            )
    except Exception as e:
        logger.warning("[delete_service] MetadataVectorDB 删除失败: %s", e)
        result.failed.append(DeleteItem(part=PART_METADATA_DB, error=str(e)))


__all__ = [
    "ALL_PARTS",
    "DeleteDocumentResult",
    "DeleteItem",
    "DocumentPaths",
    "delete_document_service",
    "document_paths",
    "find_source_pdf",
    "normalize_parts",
    "PART_BRIEF",
    "PART_GENERATED",
    "PART_IMAGES",
    "PART_JSON_DATA",
    "PART_METADATA_DB",
    "PART_REGISTRY",
    "PART_SOURCE_PDF",
    "PART_SUMMARY",
    "PART_VECTOR_DB",
]
