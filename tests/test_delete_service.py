"""delete_service 的直接用例——它是全仓库唯一的删除实现，此前 0 用例。

钉住的四类行为（Lead 指定的重点）：
1. 删干净：parts=None 时把 json_data / vector_db / images / summary / brief /
   generated_files 各产物面以及 registry 记录一并清掉，且**不动源 PDF**；
2. 删不存在的返回形状：deleted/failed 全空、registry_removed False、
   anything_done / success False——三路上层都靠这几个布尔量判 404，形状必须稳；
3. 部分产物缺失容错：缺的东西是"已删"而不是"失败"，不该进 result.failed；
4. 失败态文档也能删：注册表里 status=error / 索引不在的条目照样能删干净
   （否则失败的文档永远删不掉，就是磁盘上的死账）。

另外单独钉 safe_path 这条防线（越界名抛 ValueError、registry 里登记的越界
路径只记失败不真删）——这条是整个删除实现的安全底座，必须有用例守着。

全程只碰 tmp_path 下的假数据根：把 PathConstants.DATA_ROOT 指过去，
所有路径 helper（get_data_root / get_vector_db_path / get_brief_summary_path
/ get_metadata_db_path / get_summary_paths）都是函数内动态读取，一处生效。
"""
import json
from pathlib import Path

import pytest

from src.config import constants as const
from src.core.document_management import DocumentRegistry
from src.core.document_management import delete_service as ds


# ==================== fixture ====================

@pytest.fixture()
def data_root(tmp_path, monkeypatch):
    """把整条路径链锚到 tmp 下的假数据根。

    PathConstants.DATA_ROOT 被 get_data_root() 动态读取，改一处就够；
    相对路径时 get_data_root 会锚到项目根，所以这里给绝对路径。
    """
    root = tmp_path / "data"
    for sub in ("pdf", "json_data", "vector_db", "pdf_image", "output"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(const.PathConstants, "DATA_ROOT", str(root))
    # 坑点：DocumentRegistry() 的默认路径取的是 src.config.settings.DATA_ROOT，
    # 那是 import 期就固化的快照，只 patch PathConstants 兜不住它——真实
    # delete_document_service() 会去读写仓库里的 data/doc_registry.json。
    # 测试必须把两处一起钉住（下面那条 test_knobs_agree 守这个一致性）。
    from src.config import settings as _settings
    monkeypatch.setattr(_settings, "DATA_ROOT", root)
    return root


@pytest.fixture()
def doc(data_root):
    """造一个"四件套 + brief + source pdf + registry 记录"都齐全的文档。"""
    base = "paper.1234"
    (data_root / "json_data" / base).mkdir(parents=True, exist_ok=True)
    (data_root / "json_data" / base / "data.json").write_text("{}", encoding="utf-8")
    (data_root / "vector_db" / f"{base}_data_index").mkdir(parents=True)
    (data_root / "vector_db" / f"{base}_data_index" / "index.faiss").write_bytes(b"\0" * 8)
    (data_root / "pdf_image" / base).mkdir(parents=True)
    (data_root / "pdf_image" / base / "page1.png").write_bytes(b"png")
    (data_root / "output" / f"{base}_brief_summary.md").write_text("brief", encoding="utf-8")
    (data_root / "output" / f"{base}_summary.md").write_text("long summary", encoding="utf-8")
    (data_root / "pdf" / f"{base}.pdf").write_bytes(b"%PDF-1.7 fake")

    reg_path = data_root / "doc_registry.json"
    reg_path.write_text(json.dumps({
        "doc-1": {
            "doc_id": "doc-1",
            "doc_name": base,
            "doc_path": str(data_root / "pdf" / f"{base}.pdf"),
            "doc_type": "pdf",
            "index_path": str(data_root / "vector_db" / f"{base}_data_index"),
            "status": "completed",
            "generated_files": {
                "images": [str(data_root / "pdf_image" / base / "page1.png")],
                "json_data": str(data_root / "json_data" / base / "data.json"),
                "vector_db": str(data_root / "vector_db" / f"{base}_data_index"),
                "summaries": [str(data_root / "output" / f"{base}_summary.md")],
            },
        }
    }), encoding="utf-8")
    return base


def _reg(data_root) -> DocumentRegistry:
    return DocumentRegistry(registry_path=str(data_root / "doc_registry.json"))


# ==================== 1. 删干净 ====================

def test_delete_all_removes_every_derived_artifact(data_root, doc):
    """parts=None：各产物面齐全性——一处都不许漏（漏删就是孤儿产物）。"""
    result = ds.delete_document_service(doc)

    assert not (data_root / "json_data" / doc).exists()
    assert not (data_root / "vector_db" / f"{doc}_data_index").exists()
    assert not (data_root / "pdf_image" / doc).exists()
    assert not (data_root / "output" / f"{doc}_brief_summary.md").exists()
    assert not (data_root / "output" / f"{doc}_summary.md").exists()

    # 记账形状与"实际删了什么"要对得上
    assert result.deleted_parts >= {ds.PART_JSON_DATA, ds.PART_VECTOR_DB,
                                    ds.PART_IMAGES, ds.PART_SUMMARY, ds.PART_BRIEF}
    assert result.failed == []
    assert result.registry_removed is True
    assert result.success is True
    assert result.anything_done is True
    assert result.doc_id == "doc-1"
    assert _reg(data_root).get_by_name(doc) is None, "registry 记录必须真的注销掉"
    assert result.freed_space_mb >= 0
    assert result.requested_parts == tuple(sorted(ds.ALL_PARTS))


def test_delete_all_never_touches_source_pdf(data_root, doc):
    """全删不含源 PDF——那是用户资产，必须显式点名（三份旧实现的共同语义）。"""
    pdf = data_root / "pdf" / f"{doc}.pdf"
    ds.delete_document_service(doc)
    assert pdf.exists(), "parts=None / 'all' 都不该删掉用户传的原件"

    # "all" 这个词同样不含 source_pdf
    result = ds.delete_document_service(doc, parts=["all"], registry=_reg(data_root))
    assert ds.PART_SOURCE_PDF not in result.deleted_parts
    assert pdf.exists(), "'all' 同样不含源 PDF"


def test_delete_source_pdf_requires_explicit_flag(data_root, doc):
    pdf = data_root / "pdf" / f"{doc}.pdf"
    result = ds.delete_document_service(doc, delete_source_pdf=True, registry=_reg(data_root))
    assert not pdf.exists()
    assert ds.PART_SOURCE_PDF in result.deleted_parts
    assert any(i.part == ds.PART_SOURCE_PDF and i.path.endswith(".pdf") for i in result.deleted)

    # 单点名 pdf：只删源文件，别的不该动
    other = "another.doc"
    (data_root / "json_data" / other).mkdir(parents=True)
    (data_root / "json_data" / other / "data.json").write_text("{}", encoding="utf-8")
    only_pdf = ds.delete_document_service(other, parts=["pdf"])
    assert (data_root / "json_data" / other).exists(), "只点名 pdf 时不许顺手动 json_data"
    assert only_pdf.deleted_parts == {ds.PART_SOURCE_PDF} or only_pdf.deleted == []


def test_generated_files_path_also_reaches_registrant_paths(data_root, doc, monkeypatch):
    """registry.generated_files 里登记的产物也要真删到——这是三份旧实现的漏删点。

    造一个"约定路径已不存在、但 registry 里另有一条登记路径还在"的场景：
    删完之后那个孤儿文件必须也没了。
    """
    odd = data_root / "output" / f"{doc}_legacy_report.md"
    odd.write_text("legacy", encoding="utf-8")
    # 把登记路径改成这个约定之外的文件
    raw = json.loads((data_root / "doc_registry.json").read_text(encoding="utf-8"))
    raw["doc-1"]["generated_files"]["summaries"] = [str(odd)]
    (data_root / "doc_registry.json").write_text(json.dumps(raw), encoding="utf-8")

    ds.delete_document_service(doc, registry=DocumentRegistry(
        registry_path=str(data_root / "doc_registry.json")))
    assert not odd.exists(), "generated_files 登记的路径漏删就会留孤儿文件"


# ==================== 2. 不存在文档的返回形状 ====================

def test_delete_nonexistent_document_shape(data_root):
    result = ds.delete_document_service("never.ever.indexed")

    assert result.doc_name == "never.ever.indexed"
    assert result.doc_name_base == "never.ever.indexed"
    assert result.doc_id is None
    assert result.doc_info is None
    assert result.deleted == []
    assert result.failed == []
    assert result.registry_removed is False
    # 三路上层都拿这两个布尔量判 404 / partial / False，形状不能漂
    assert result.anything_done is False
    assert result.success is False
    assert result.freed_space_mb == 0.0
    assert result.deleted_parts == set()


def test_delete_second_time_reports_nothing_done(data_root, doc):
    """幂等：第二次调用安全（不炸、不报错），但如实说"什么都没做"。

    上层若把它当成失败去报错，UI 上就会出现"再点一次删除反而报错"——
    这里钉住 anything_done=False / success=False / failed 全空。
    """
    assert ds.delete_document_service(doc).anything_done is True
    again = ds.delete_document_service(doc)
    assert again.deleted == [] and again.failed == []
    assert again.registry_removed is False
    assert again.anything_done is False and again.success is False


def test_delete_empty_parts_is_a_no_op_not_an_error(data_root, doc):
    """parts=[] 应该被翻译成"什么都不删"，而不是删全部、也不是报错。"""
    result = ds.delete_document_service(doc, parts=[])
    assert result.deleted == []
    assert result.requested_parts == ()
    assert result.anything_done is False


# ==================== 3. 部分产物缺失的容错 ====================

def test_delete_with_most_artifacts_missing_leaves_no_failures(data_root):
    """只有 json_data 在、其它都没写过——缺的是"已删"，不是"失败"。"""
    base = "half.done"
    (data_root / "json_data" / base).mkdir(parents=True, exist_ok=True)
    (data_root / "json_data" / base / "data.json").write_text("{}", encoding="utf-8")
    result = ds.delete_document_service(base, registry=_reg(data_root))
    assert not (data_root / "json_data" / base).exists()
    assert result.failed == [], "缺失的产物不该进 failed"
    assert result.deleted_parts == {ds.PART_JSON_DATA}
    assert result.success is True


def test_delete_only_summary_present_counts_summary_parts(data_root):
    base = "summary.only"
    (data_root / "output" / f"{base}_brief_summary.md").write_text("b", encoding="utf-8")
    result = ds.delete_document_service(base, parts=["summary"])
    assert not (data_root / "output" / f"{base}_brief_summary.md").exists()
    assert result.failed == []
    # brief 文件在"只点名 summary"时也算在 summary 名下（并集语义）
    assert result.deleted_parts == {ds.PART_SUMMARY}


def test_delete_registry_entry_gone_keeps_files_cleanable(data_root, doc):
    """registry 记录先没了（并发/手工清过）：文件照样删，registry_removed 走
    "目标已达成的成功"，而不是失败。"""
    (data_root / "doc_registry.json").write_text("{}", encoding="utf-8")
    result = ds.delete_document_service(doc, registry=_reg(data_root))
    assert not (data_root / "vector_db" / f"{doc}_data_index").exists()
    assert result.failed == []
    assert result.anything_done is True


# ==================== 4. 失败态文档也能删 ====================

def test_delete_failed_status_document(data_root):
    """status=error / 索引不存在的条目必须也能删干净，否则失败文档就是死账。"""
    base = "crashed.doc"
    (data_root / "json_data" / base).mkdir(parents=True)
    (data_root / "json_data" / base / "data.json").write_text("{}", encoding="utf-8")
    (data_root / "doc_registry.json").write_text(json.dumps({
        "doc-err": {
            "doc_id": "doc-err", "doc_name": base, "doc_type": "pdf",
            "doc_path": str(data_root / "pdf" / f"{base}.pdf"),
            "index_path": "", "status": "error",
            "processing_stages": {"register": {"status": "failed", "output_files": []}},
            "generated_files": {},
        }
    }), encoding="utf-8")
    (data_root / "pdf" / f"{base}.pdf").write_bytes(b"%PDF-1.7 partial")

    result = ds.delete_document_service(base, registry=_reg(data_root))
    assert not (data_root / "json_data" / base).exists()
    assert result.registry_removed is True
    assert result.doc_id == "doc-err"
    assert result.failed == []
    assert _reg(data_root).get_by_name(base) is None


def test_delete_document_whose_index_path_points_nowhere(data_root):
    """有记录、index_path 是个不存在的路径（索引半途而废）——不能因此拒删。"""
    base = "ghost.index"
    (data_root / "vector_db" / f"{base}_data_index").mkdir(parents=True)
    (data_root / "doc_registry.json").write_text(json.dumps({
        "doc-ghost": {"doc_id": "doc-ghost", "doc_name": base, "doc_type": "pdf",
                      "index_path": str(data_root / "vector_db" / "does_not_exist"),
                      "status": "completed", "generated_files": {}}
    }), encoding="utf-8")
    result = ds.delete_document_service(base, registry=_reg(data_root))
    assert not (data_root / "vector_db" / f"{base}_data_index").exists()
    assert result.registry_removed is True and result.failed == []


# ==================== safe_path 防线 ====================

@pytest.mark.parametrize("bad_name", [
    "../evil", "../../etc/passwd", "a/b", "a\\b", "", "   ", ".hidden",
    "doc.pdf/../../etc", "..",
])
def test_delete_rejects_unsafe_doc_names(data_root, bad_name):
    """非法 doc_name 一律 ValueError（UI 翻 400 / CLI 返 False），
    而且是在动文件系统之前就挡住。"""
    canary = data_root.parent / "canary.txt"
    canary.write_text("do not touch", encoding="utf-8")
    (data_root / "json_data").mkdir(exist_ok=True)

    with pytest.raises(ValueError):
        ds.delete_document_service(bad_name)
    assert canary.exists()


def test_document_paths_stay_inside_data_root(data_root, doc):
    paths = ds.document_paths(doc)
    root = data_root.resolve()
    for p in (paths.json_data, paths.vector_db, paths.images, paths.brief,
              paths.source_pdf, *paths.summaries):
        assert Path(p).resolve().is_relative_to(root), p
    # "foo.pdf" 与 "foo" 必须落到同一个基名
    assert ds.document_paths(f"{doc}.pdf").doc_name_base == doc


def test_generated_file_recorded_outside_data_root_is_refused(data_root, doc, monkeypatch):
    """registry 里被写了个数据目录之外的路径——只记失败，绝不 rmtree 出去。"""
    outside = data_root.parent / "outside_dir"
    outside.mkdir()
    (outside / "keepme.txt").write_text("mine", encoding="utf-8")

    raw = json.loads((data_root / "doc_registry.json").read_text(encoding="utf-8"))
    raw["doc-1"]["generated_files"]["images"] = [str(outside / "keepme.txt")]
    (data_root / "doc_registry.json").write_text(json.dumps(raw), encoding="utf-8")

    result = ds.delete_document_service(doc, registry=_reg(data_root))
    assert (outside / "keepme.txt").exists(), "越界登记路径绝不能真的删"
    assert any(ds.PART_IMAGES == i.part and "越" in (i.error or "") for i in result.failed)


def test_find_source_pdf_prefers_data_dir_then_registry(data_root, doc):
    p = ds.find_source_pdf(doc)
    assert p is not None and p.name == f"{doc}.pdf"

    # data/pdf 下没有时，回退到 registry 的 doc_path
    (data_root / "pdf" / f"{doc}.pdf").unlink()
    assert ds.find_source_pdf(doc, {"doc_path": str(data_root / "json_data")}) is None
    ext = data_root / "uploaded_elsewhere.pdf"
    ext.write_bytes(b"%PDF-1.7")
    assert ds.find_source_pdf(doc, {"doc_path": str(ext)}) == ext
    # 非法名不抛异常，按"找不到"处理
    assert ds.find_source_pdf("../nope") is None


# ==================== 部件词汇表 / 别名 ====================

def test_normalize_parts_aliases_and_unknowns():
    assert ds.normalize_parts(None) == set(ds.ALL_PARTS)
    assert ds.normalize_parts(["json"]) == {ds.PART_JSON_DATA}
    assert ds.normalize_parts(["VECTOR", "  Image  ", "faiss", "output"]) == {
        ds.PART_VECTOR_DB, ds.PART_IMAGES, ds.PART_SUMMARY}
    assert ds.normalize_parts(["pdf"]) == {ds.PART_SOURCE_PDF}
    # 未知部件被忽略而不是报错（数据管理页既有行为）
    assert ds.normalize_parts(["totally_unknown_part"]) == set()
    # "all" 展开后仍不含 source_pdf
    assert "source_pdf" not in ds.normalize_parts(["all"])


def test_full_delete_set_alone_注销registry(data_root, doc):
    """没点名 registry，但四件套齐了 → 视为完全删除，一样注销（既有规则）。"""
    result = ds.delete_document_service(doc, parts=["json_data", "vector_db", "images", "summary"],
                                        registry=_reg(data_root))
    assert result.registry_removed is True
    assert _reg(data_root).get_by_name(doc) is None


def test_single_part_keeps_registry_record(data_root, doc):
    result = ds.delete_document_service(doc, parts=["json_data"], registry=_reg(data_root))
    assert result.registry_removed is False
    assert _reg(data_root).get_by_name(doc) is not None


def test_metadata_db_failure_does_not_block_registry注销(data_root, doc, monkeypatch):
    """MetadataVectorDB 删失败只记一条失败，registry 注销照做——顺序上的
    约定（先 metadata 后 registry）不该把主流程拖挂。"""
    (data_root / "vector_db" / "_metadata").mkdir(parents=True, exist_ok=True)
    (data_root / "vector_db" / "_metadata" / "index.faiss").write_bytes(b"\0" * 8)

    import src.core.vector_db.metadata_db as mdb

    class BoomDB:
        def delete_document(self, doc_id):
            raise RuntimeError("metadata 库坏了")

    monkeypatch.setattr(mdb, "MetadataVectorDB", BoomDB)
    result = ds.delete_document_service(doc, registry=_reg(data_root))
    assert result.registry_removed is True
    assert any(i.part == ds.PART_METADATA_DB and i.error for i in result.failed)
    assert result.success is False, "有失败项就不算完全成功，上层要能说 partial"


def test_metadata_skipped_when_db_never_initialized(data_root, doc, monkeypatch):
    """元数据库没建过就跳过——别为了"删"反而把空索引初始化出来（CLI 旧毛病）。"""
    import src.core.vector_db.metadata_db as mdb

    called = {"n": 0}

    class ShouldNotConstruct:
        def __init__(self, *a, **k):
            called["n"] += 1

        def delete_document(self, doc_id):
            return True

    monkeypatch.setattr(mdb, "MetadataVectorDB", ShouldNotConstruct)
    result = ds.delete_document_service(doc, registry=_reg(data_root))
    assert called["n"] == 0
    assert not any(i.part == ds.PART_METADATA_DB for i in result.deleted)


# ==================== 向量库缓存联动 ====================

def test_vector_db_cache_invalidated_on_delete(data_root, doc, monkeypatch):
    """删完向量库要作废读侧进程内缓存，否则同名路径会命中旧 FAISS 对象。"""
    seen = []
    import src.core.vector_db.vector_db_client as vdb
    monkeypatch.setattr(vdb, "invalidate_vector_db_cache",
                        lambda p: seen.append(str(p)), raising=False)
    ds.delete_document_service(doc, registry=_reg(data_root))
    assert any(f"{doc}_data_index" in s for s in seen), \
        "vector_db 目录被删后必须显式失效缓存"


def test_data_root_knobs_agree(data_root):
    """两个"数据根"入口必须同源：constants.get_data_root() 动态读
    PathConstants.DATA_ROOT，而 DocumentRegistry() 默认路径读
    settings.DATA_ROOT——import 期快照。只 patch 一个就会让删除路径
    与注册表路径各指一处，测试和运行时的行为就此分叉（这里同时钉住）。
    """
    from src.config import settings as _settings
    assert Path(_settings.DATA_ROOT) == const.get_data_root()
