"""共享 SSRF 护栏——本应用所有"由外部内容给出的 URL 去拉字节"的入口共用。

原实现住在 briefs.py 的 /fetch-pdf 一处；pipeline 的 process_pdf_queue 下载
面是同类入口，却只有 urllib 默认的重定向跟随、没有 scheme/地址校验，两边
规则迟早漂移（2026-11-25 审计点名的"与既有加固面不一致"条目）。规则在
本模块单源：scheme 限 http(s)、主机解析后过黑名单、逐跳复验、响应体上限。
只挡内网，不做白名单——arxiv 与公网照常可达，这与应用"本地无鉴权"的信任
模型一致。

两个已知边界，沿用 briefs.py 时代的声明：
  * DNS 重绑定 TOCTOU：解析校验与真正建连之间有时间窗，承认存在、不为此
    单造连接级锁。
  * 6to4/Teredo 已入黑名单兜底（2002::/16、2001::/32）。

异常约定：本模块一律 raise ValueError（中文 message 自带拒绝原因），
UI 侧转 HTTPException 由调用层完成，pipeline 侧让它直接当失败记账——
两边拿的是同一条规则，不是两套话。
"""
from __future__ import annotations

import ipaddress
import os
import socket
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

# loopback(127/8, ::1)、RFC1918、link-local 含 169.254.169.254 元数据、
# 运营商级 NAT 100.64/10、ULA、文档/保留段、IPv4-mapped IPv6。
# 6to4/Teredo：内网地址被嵌进 IPv6 文本时 ::ffff: 映射解不出
# （2002:7f00:1:: 不算 ipv4_mapped），is_reserved 也常漏这两段——
# 显式入黑名单兜底，别让"IPv6 写法"成为绕过内网禁令的正门。
BLOCKED_NETS = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "169.254.0.0/16", "100.64.0.0/10", "0.0.0.0/8", "240.0.0.0/4",
    "::1/128", "fc00::/7", "fe80::/10", "192.0.0.0/24", "198.18.0.0/15",
    "2002::/16", "2001::/32",
    "198.51.100.0/24", "203.0.113.0/24",
))

DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
MAX_REDIRECTS = 5
MAX_BYTES = 100 * 1024 * 1024  # 与 briefs /fetch-pdf 同源的上限


def address_is_public(ip) -> bool:
    """单个地址是否允许抓取——私有/回环/链路本地/保留/组播一律拒绝。"""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 这类映射地址按 IPv4 判
    if isinstance(ip, ipaddress.IPv4Address):
        return not (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified
                    or any(ip in n for n in BLOCKED_NETS if n.version == 4))
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast
                or any(ip in n for n in BLOCKED_NETS if n.version == 6))


def resolve_and_check(host: str) -> None:
    """解析主机名并逐地址校验；解析失败按拒绝处理（宁挡错不误放）。"""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, socket.herror, UnicodeError, OSError) as exc:
        raise ValueError(f"主机 {host} 解析失败，拒绝下载：{exc}") from exc
    addrs = {info[4][0].split("%", 1)[0] for info in infos}
    if not addrs:
        raise ValueError(f"主机 {host} 没有可用地址")
    for addr in addrs:
        if not address_is_public(ipaddress.ip_address(addr)):
            raise ValueError(f"目标 {host} 指向内网/保留地址 {addr}，已拒绝")


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def ensure_public_url(url: str) -> None:
    """scheme + 主机地址双重校验。违规 raise ValueError。"""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError as exc:  # 畸形 IPv6 字面量等
        raise ValueError(f"URL 无法解析：{exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise ValueError("url 的协议必须是 http(s)")
    if not host:
        raise ValueError("URL 里没有主机名")
    if is_ip_literal(host):
        if not address_is_public(ipaddress.ip_address(host)):
            raise ValueError(f"目标 {host} 是内网/保留地址，已拒绝")
        return
    resolve_and_check(host)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """重定向必须逐跳复验地址——urllib 默认的自动跟随正是"第一跳公网、
    第二跳跳进 127.0.0.1"的正门，这里把它关掉，由 fetch 自己跟。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_bytes(url: str, *, timeout: int = 60, max_bytes: int = MAX_BYTES,
                headers: dict | None = None) -> bytes:
    """带守卫的 GET：scheme/地址逐跳校验、跟随上限 MAX_REDIRECTS 跳、
    响应体上限 max_bytes（超限即断，不无上限拉流）。失败 ValueError。
    """
    opener = urllib.request.build_opener(_NoRedirect())
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        ensure_public_url(current)
        req = urllib.request.Request(
            current, headers={"User-Agent": DEFAULT_UA, **(headers or {})})
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                raise ValueError(f"下载失败 {e.code}：{url}") from e
            loc = e.headers.get("Location")
            if not loc:
                raise ValueError(f"{e.code} 重定向没有 Location：{url}") from e
            current = urljoin(current, loc)
            continue
        try:
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError(f"响应体超过 {max_bytes} 字节上限，已中断")
            return data
        finally:
            resp.close()
    raise ValueError(f"重定向超过 {MAX_REDIRECTS} 跳，已放弃")


def fetch_to_file(url: str, dest_path, *, timeout: int = 60,
                  max_bytes: int = MAX_BYTES, headers: dict | None = None) -> None:
    """fetch_bytes 的落盘版：先整段取回（上限已管住），再临时名 +
    os.replace 原子换名——中途失败不留半个文件。"""
    import threading

    data = fetch_bytes(url, timeout=timeout, max_bytes=max_bytes, headers=headers)
    dest = str(dest_path)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = (f"{dest}.part.{os.getpid()}.{threading.get_ident()}."
           f"{os.urandom(4).hex()}")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
