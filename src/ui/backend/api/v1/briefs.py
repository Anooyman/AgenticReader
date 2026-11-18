"""简报浏览 REST API——每日简报的读取与按需加载。改自 ai-research-pipeline
的 webapp/api/briefs.py。

这一组接口让 WebUI 成为操作入口：先浏览、再挑感兴趣的加载，而不是像批
处理脚本那样一跑就是把当天全部条目都处理掉（十几篇 PDF 要四五个小时）。

GET 是纯读（解析 HTML，不写任何状态），POST 才会登记 queue 并派发后台
任务——任务本身由 job_runner 串行执行。
"""
import asyncio
import ipaddress
import logging
import os
import re
import socket
import threading
import uuid
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.ui.backend.services import briefs_data, job_runner
from ...config import PDF_DIR

router = APIRouter()

# 轻量入库的日期参数——沿用原 /memory 页 /load-jobs 的 _normalize_dates
# 语义：dates 列表或单个串、格式校验、去重排序、跨日单次上限 40。
# 格式错误挡在入队之前，别让它晚一步在 job 里才炸出来。
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_DATES_PER_REQUEST = 40


def _normalize_dates(body: dict) -> list:
    """dates: [...] / "YYYY-MM-DD"，或旧参数 coverage_date 单值（兼容保留）。"""
    raw = (body or {}).get("dates")
    if raw is None:
        raw = (body or {}).get("coverage_date")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400,
                            detail="dates: 需要非空的 YYYY-MM-DD 日期列表（或 coverage_date 单值）")
    valid = sorted({d.strip() for d in raw if isinstance(d, str) and _DATE_RE.match(d.strip())})
    if not valid:
        raise HTTPException(status_code=400, detail="dates 中没有合法的 YYYY-MM-DD 条目")
    if len(valid) > _MAX_DATES_PER_REQUEST:
        raise HTTPException(status_code=400,
                            detail=f"一次最多排 {_MAX_DATES_PER_REQUEST} 个日期，请分批")
    return valid


@router.get("/memory-status")
async def get_memory_status():
    """各日期的真实入库计数：{"dates": {"2026-11-12": {"aatf": 37, "heavy_done": 2}, ...}}

    供 /briefs 页区分"有 HTML 未入库 / 有 HTML 已入库 / 无 HTML"三种状态
    （无 HTML 的日期根本不会出现在列表里）。数据来源是 A 自库行 + queue
    事实，**不是任务账本**——bridge 时代的 done ≠ A 自库有数据，按账本
    显示只会造出满屏"已入库"的假象（state-auditor 审计实锤）。
    纯读，LanceDB 全行扫描是函数级 to_thread，不阻塞事件循环。"""
    counts = await asyncio.to_thread(briefs_data.date_memory_counts)
    return {"dates": counts}


@router.get("/dates")
async def get_dates():
    return {"dates": briefs_data.available_dates()}


@router.get("/cards")
async def get_cards(coverage_date: str):
    return briefs_data.load_cards(coverage_date)


@router.post("/load")
async def post_load(body: dict):
    """把勾选的条目登记进 queue 并派发处理任务。

    每个条目一个任务，串行跑：下载 -> 索引 -> 多维度问答 -> 摘要 -> 入库。
    PDF 单篇 15-30 分钟，所以这里只负责入队，立刻返回，进度靠 /api/v1/jobs
    轮询。"""
    coverage_date = (body or {}).get("coverage_date")
    item_ids = (body or {}).get("item_ids") or []
    if not coverage_date:
        raise HTTPException(status_code=400, detail="coverage_date is required")
    if not item_ids:
        raise HTTPException(status_code=400, detail="item_ids is required")

    to_run = await briefs_data.register_for_processing(coverage_date, item_ids)
    jobs = [
        await job_runner.enqueue(
            "process_item", entry["item_id"],
            title=entry["title"], item_type=entry["type"],
        )
        for entry in to_run
    ]
    return {"requested": len(item_ids), "queued": len(jobs), "jobs": jobs}


@router.post("/sync-memory")
async def post_sync_memory():
    """把所有还没入库的摘要补灌进 memory。

    正常路径下每篇处理完会自动入库，这个按钮是给历史欠账用的——比如
    memory 库被清空过、或早期处理的条目当时 inline ingest 失败了。"""
    job = await job_runner.enqueue("sync_memory", "__all_pending__",
                                   title="补灌全部未入库摘要")
    return {"job": job}


@router.post("/light-load")
async def post_light_load(body: dict):
    """轻量入库：这一天的简报卡片直接写进 A 自库 memory 的 namespace
    AATF，走 load_brief_date 任务——不下载 PDF、不做多维问答，零 LLM
    调用，一天几秒到几十秒就完事。

    与 /load 的分工（取代原 /memory 页的日期加载）：
      /load        重管线，条目级，产摘要 + 入 ai-research；
      /light-load  轻量级，日期级，卡片导读原文直接入 AATF。
    驱动分派在 gateway.load_brief_date（缺省 local；env
    MEMORY_BRIEF_DRIVER=bridge 时回到外部 LLM-Memory 桥，仅作兜底）。

    日期参数：{dates: [...]} 一次给多天（沿用原 /load-jobs 的批量语义），
    或 {coverage_date: "YYYY-MM-DD"} 单日兼容旧调用。逐日一个
    load_brief_date job——job_runner 对同一 target 直接返回在飞的旧 job，
    重复点同一个日期不会跑两遍。"""
    dates = _normalize_dates(body)
    jobs = [await job_runner.enqueue("load_brief_date", d, title=f"轻量入库 {d}")
            for d in dates]
    return {"requested": len(dates), "queued": len(jobs),
            "dates": dates, "jobs": jobs}


# ---- 论文"下载入库"：把卡片 PDF 拉进 data/pdf 并触发本地索引 --------------
# 原 /memory 页对话回复里「⬇下载入库」能力的本地化替身——旧实现靠 B 侧
# deepread 端点下载，本地库路线下这一步必须自己完成：下载→落 data/pdf→
# 复用 documents.py 的同一条 IndexingAgent 后台流。
_FETCH_PDF_MAX_BYTES = 100 * 1024 * 1024
_FETCH_MAX_REDIRECTS = 5
_NAME_SAFE_RE = re.compile(r"^[\w][\w.+ -]*$", re.UNICODE)
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(?:v\d+)?(?:[.#][^/?]*)?(?:[?#].*)?$",
                           re.IGNORECASE)

logger = logging.getLogger(__name__)


def _tmp_name(target):
    """本次下载独占的临时文件名——沿用 write_json_atomic 的 pid+tid 约定，
    再加 8 位 hex 熵：本端点是 async 的，两个并发协程跑在同一条事件循环
    线程上、tid 相同，光靠 pid+tid 会撞名（json_io 是同步栈，够它用；这里
    不够）。固定名 `.part` 的坏处不只是互相抢 rename——失败分支的
    unlink(missing_ok) 会删掉另一路正在写的手柄，最终 os.replace 出一份
    交错损坏的 PDF，而魔数只校验了首块，没人能发现。
    """
    return target.with_name(
        f"{target.name}.part.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}"
    )


# SSRF 护栏：拒绝指向内网/保留地址的目标。信任级别与 SearchAgent 的网页
# 抓取面同级——本应用按本地无鉴权设计，但 fetch-pdf 是"拿一个由模型/外部
# 内容给出的 URL 去拉字节"，属于本端点里唯一真正的入站请求发起点，所以
# 有意比 SearchAgent 那侧多加一层地址限制：只挡内网，不做白名单，
# arxiv 等公网镜像照常可用。
#
# 覆盖：loopback(127/8, ::1)、RFC1918、link-local 含 169.254.169.254 元数据、
# 运营商级 NAT 100.64/10、ULA、文档/保留段、IPv4-mapped IPv6。
#
# 两个已知边界，写清楚免得被当成完整实现：
#   * DNS 重绑定：解析后到真正建连之间有时间窗，若攻击者控制的 DNS 记录
#     在这中间翻成内网 IP，这里挡不住（要堵需要连接时按解析结果直接
#     建连，代价明显大于本端点的威胁面）。
#   * 逐跳校验：重定向是我们自己跟的，每一跳都重新过这里，不会"第一跳
#     公网、第二跳跳进 127.0.0.1"。
_BLOCKED_NETS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "100.64.0.0/10", "0.0.0.0/8", "240.0.0.0/4",
    "::1/128", "fc00::/7", "fe80::/10", "192.0.0.0/24", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24",
))


def _address_is_public(ip) -> bool:
    """单个地址是否允许抓取——私有/回环/链路本地/保留/组播一律拒绝。"""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 这类映射地址按 IPv4 判
    if isinstance(ip, ipaddress.IPv4Address):
        return not (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified
                    or any(ip in n for n in _BLOCKED_NETS if n.version == 4))
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast
                or any(ip in n for n in _BLOCKED_NETS if n.version == 6))


def _resolve_and_check(host: str) -> None:
    """解析主机名并逐地址校验；解析失败按拒绝处理（宁挡错不误放）。"""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, socket.herror, UnicodeError, OSError) as exc:
        # getaddrinfo 的失败面比 gaierror 宽（herror / UnicodeError / 其它
        # OSError），一律按"拒绝"处理：解析不通的主机没有理由放它过去。
        raise HTTPException(status_code=400,
                            detail=f"主机 {host} 解析失败，拒绝下载：{exc}") from exc
    addrs = {info[4][0].split("%", 1)[0] for info in infos}
    if not addrs:
        raise HTTPException(status_code=400, detail=f"主机 {host} 没有可用地址")
    for addr in addrs:
        if not _address_is_public(ipaddress.ip_address(addr)):
            raise HTTPException(status_code=400,
                                detail=f"目标 {host} 指向内网/保留地址 {addr}，已拒绝")


def _guard_url(url: str) -> None:
    """URL 的 scheme + 主机地址双重校验（同步，调用方放 to_thread）。"""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError as exc:  # 畸形 IPv6 字面量等
        raise HTTPException(status_code=400, detail=f"URL 无法解析：{exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="url 的协议必须是 http(s)")
    if not host:
        raise HTTPException(status_code=400, detail="URL 里没有主机名")
    if _is_ip_literal(host):
        if not _address_is_public(ipaddress.ip_address(host)):
            raise HTTPException(status_code=400, detail=f"目标 {host} 是内网/保留地址，已拒绝")
        return
    _resolve_and_check(host)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _pdf_doc_name_from_url(url: str) -> str:
    """从 URL 推 PDF 的入库文档名（不带 .pdf 后缀）。

    arXiv 优先：id 走 briefs_parser.arxiv_id_no_version——与重管线
    process_pdf_queue 的 doc_name=item_id 约定同源，同一个条目在重管线
    和这里入的库指向同一个文档名，registry 不裂。非 arXiv 取路径末段
    消毒；认不出返回空串，由调用方 400。
    """
    m = _ARXIV_URL_RE.search(url)
    if m:
        from src.pipeline.briefs_parser import arxiv_id_no_version
        return arxiv_id_no_version(m.group(1))
    from urllib.parse import urlparse, unquote
    last = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    last = unquote(last)
    if last.lower().endswith(".pdf"):
        last = last[:-4]
    if not last or not _NAME_SAFE_RE.match(last):
        return ""
    return last


def _index_status_of(doc_name_no_suffix: str) -> tuple[str, str]:
    """问 registry：这个条目索引到什么地步了，返回 (state, registry_doc_name)。

    state ∈ "indexed" / "not_indexed" / "indexed_elsewhere" / "unknown"：
      * indexed            —— 有精确同名记录且 index_path 在。判据与
                               documents.list / get_pending_pdfs 完全同源，
                               别自己再发明一套；
      * not_indexed        —— 有同名记录但索引不在，即跑挂过或半途而废；
      * indexed_elsewhere  —— 同名记录没有，但有个带版本号的兄弟条目
                               （2607.11185 → 2607.11185v1）已经索引好了。
                               注意那是**另一个文件**（data/pdf/ 里躺着的是
                               2607.11185v1.pdf，实测 registry 的名字与磁盘
                               文件名一致），所以既不能说这条已索引（虚假宣
                               称），也不该再排一次索引——同一篇论文白烧一遍
                               LLM，registry 还裂成两条；
      * unknown            —— 压根没记录，多半是用户自己把 PDF 丢进
                               data/pdf 的。不算失败，UI 别刷红字。

    认兄弟条目是必要的：doc_name 有两种历史写法——重管线与 fetch-pdf 都走
    briefs_parser 的 arxiv_id_no_version 去版本号，而 documents 页手动上传
    那批保留着版本号。只认精确名，用户点一次"下载入库"就会在同一篇论文上
    再开一份索引。
    """
    try:
        from src.core.document_management.registry import DocumentRegistry
        records = DocumentRegistry().list_all()
    except Exception:  # noqa: BLE001 - registry 缺失不影响下载入库这条路
        logger.warning("fetch-pdf: 读取 registry 失败，索引状态按 unknown 计", exc_info=True)
        return "unknown", ""

    sibling_indexed = ""
    exact_seen = False
    for rec in records:
        name = str(rec.get("doc_name") or "")
        if not name:
            continue
        index_ok = bool(rec.get("index_path")) and os.path.exists(rec["index_path"])
        if name == doc_name_no_suffix:
            exact_seen = True
            if index_ok:
                return "indexed", name
        elif re.fullmatch(rf"{re.escape(doc_name_no_suffix)}v\d+", name, re.IGNORECASE) and index_ok:
            sibling_indexed = sibling_indexed or name
    if exact_seen:
        return "not_indexed", doc_name_no_suffix
    return ("indexed_elsewhere", sibling_indexed) if sibling_indexed else ("unknown", "")


def _start_index_task(background_tasks: BackgroundTasks, doc_name: str) -> None:
    """接上 documents 的同一条索引后台流。

    provider=None 走 settings.resolve_provider 链（/config → env → openai），
    本文件别的地方也不自己写死 provider。preset 取 /config 页当前值——
    fetch-pdf 下的论文与手动上传的是同一类活，没有理由独享 "high" 这个
    写死值（documents.py 那边同样是配置驱动）。
    """
    from src.ui.backend.api.v1.documents import _index_document_task
    try:
        from src.ui.backend.api.v1.config import get_current_pdf_preset
        preset = get_current_pdf_preset()
    except Exception:  # noqa: BLE001 - 配置层出问题时退到默认，别挡住入库
        preset = "high"
    background_tasks.add_task(_index_document_task, doc_name=doc_name,
                              provider=None, pdf_preset=preset)


@router.post("/fetch-pdf")
async def post_fetch_pdf(body: dict, background_tasks: BackgroundTasks):
    """下载论文 PDF 到 data/pdf/ 并启动索引，返回 {doc_name, status, indexed?}。

    - status="exists"：文件已在 data/pdf，同时如实带回索引状态——
      indexed=True 直接完事；未索引的顺手补排一次索引（这正是这个按钮
      该有的语义）。否则前端（paper-ingest.js）只会死等"出现在已索引
      列表"，一个之前索引失败过的条目要等满 30 分钟才等到"继续检查索引"。
    - status="started"：刚下载完，索引已进后台任务流
    - 校验 %PDF- 魔数 + 100MB 上限 + 目标不得指向内网/保留地址
    - 重定向由我们自己逐跳跟，每一跳都重新过 SSRF 校验（见 _guard_url 注记）
    """
    url = ((body or {}).get("url") or "").strip()
    # force: true —— 强制重下一遍，跳过"文件已存在"这条捷径。给前端的
    # "重试/继续检查索引"用的：文件可能是半截的（截断/写坏），光等索引
    # 永远等不出来，重试总得有点新动作。
    # TODO(review-beta 交接给 lead)：ui 侧要真用上得在 api.js 的
    # briefs.fetchPdf 上把这个键透传出来——api.js 不在本任务的
    # writeScopes 里，我没动它，别把它当成已接通。
    force = bool((body or {}).get("force"))
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url 必须是 http(s) 链接")
    doc_base = _pdf_doc_name_from_url(url)
    if not doc_base:
        raise HTTPException(status_code=400, detail="URL 推不出安全的 PDF 文件名")

    target = PDF_DIR / f"{doc_base}.pdf"
    if target.exists() and not force:
        state, registry_name = _index_status_of(doc_base)
        payload = {"status": "exists", "doc_name": target.name,
                   "indexed": state == "indexed", "index_state": state}
        # 名字对不上时把 registry 的真名给出去，前端轮询 documents.list
        # 才有得比（paper-ingest.js 拿它当第二个比对键）。
        if registry_name:
            payload["registry_doc_name"] = registry_name
        if state == "indexed":
            return payload
        if state == "indexed_elsewhere":
            # 同一篇论文的带版本号条目已入库，不再排索引（否则 registry 裂两条、
            # LLM 白烧一遍）；registry_doc_name 已带在上面，前端照它轮询就能看到。
            payload["note"] = (f"该文件的索引还没做过，但同一篇论文已按 {registry_name} "
                               f"入库存档，无需重复索引")
            return payload
        _start_index_task(background_tasks, target.name)
        payload["reindex_started"] = True
        payload["note"] = ("文件已在 PDF 库，但此前索引未完成/失败，已重新排队索引"
                           if state == "not_indexed" else "文件已在 PDF 库，索引排队中")
        return payload

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = _tmp_name(target)
    downloaded = 0
    try:
        # follow_redirects 关掉：开着自己跳的话，第二跳不经我们手，SSRF
        # 校验就成了只看第一跳的摆设。
        async with httpx.AsyncClient(follow_redirects=False,
                                     timeout=httpx.Timeout(30.0, read=120.0),
                                     headers={"User-Agent": "Mozilla/5.0 (AgenticReader brief fetch)"}) as client:
            current = url
            for _hop in range(_FETCH_MAX_REDIRECTS + 1):
                await asyncio.to_thread(_guard_url, current)
                async with client.stream("GET", current) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location") or ""
                        if not location:
                            raise HTTPException(status_code=502, detail="重定向缺 Location")
                        current = urljoin(current, location)
                        continue
                    if resp.status_code >= 400:
                        raise HTTPException(status_code=502,
                                            detail=f"下载失败：HTTP {resp.status_code}")
                    first = True
                    with tmp_path.open("wb") as f:
                        async for chunk in resp.aiter_bytes(1 << 16):
                            if first:
                                if not chunk.startswith(b"%PDF-"):
                                    raise HTTPException(status_code=400,
                                                        detail="目标不是有效的 PDF 文件")
                                first = False
                            downloaded += len(chunk)
                            if downloaded > _FETCH_PDF_MAX_BYTES:
                                raise HTTPException(status_code=413, detail="PDF 超过 100MB 上限")
                            f.write(chunk)
                    # 正常收尾：原子换名，再不动它自己那份 tmp
                    tmp_path.replace(target)
                    tmp_path = None  # 已改名，finally 别再 unlink
                    break
            else:
                raise HTTPException(status_code=502, detail=f"重定向超过 {_FETCH_MAX_REDIRECTS} 跳")
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"下载失败：{exc}") from exc
    except Exception as e:  # noqa: BLE001 - 落盘/清理等本地错误
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        # 只删自己这一路的 tmp；失败/取消都走这里，不会碰并发的另一路
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("fetch-pdf: 临时文件 %s 清理失败: %s", tmp_path, exc)

    _start_index_task(background_tasks, target.name)
    return {"status": "started", "doc_name": target.name}
