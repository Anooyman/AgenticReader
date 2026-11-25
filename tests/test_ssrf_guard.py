"""SSRF 护栏的单元钉——规则在 src/utils/ssrf_guard.py 单源，两个下载入口
（briefs /fetch-pdf 与 process_pdf_queue）共享同一张黑名单。

这里只做"判定面"的验证：scheme、内网字面量、6to4/Teredo 变体、解析失败
按拒绝处理。网络不真出去（字面量不需要 DNS，域名面用假 getaddrinfo）。
"""
import ipaddress
import socket

import pytest

from src.utils import ssrf_guard


def test_rejects_non_http_schemes():
    for bad in ("file:///etc/passwd", "ftp://example.com/x", "gopher://x", ""):
        with pytest.raises(ValueError):
            ssrf_guard.ensure_public_url(bad)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x.pdf",
    "http://10.0.0.5/x",
    "http://172.16.3.4/x",
    "http://192.168.1.1/x",
    "http://169.254.169.254/latest/meta-data",
    "http://[::1]/x",
    "http://100.64.0.1/x",
])
def test_rejects_internal_ip_literals(url):
    with pytest.raises(ValueError):
        ssrf_guard.ensure_public_url(url)


def test_rejects_v6_variant_forms_of_internal_addresses():
    """6to4/Teredo 把内网 IP 嵌进 IPv6 文本，::ffff: 映射解不出、
    is_reserved 常漏——必须靠黑名单段本身拦住。"""
    assert not ssrf_guard.address_is_public(ipaddress.ip_address("2002:7f00:1::"))
    assert not ssrf_guard.address_is_public(ipaddress.ip_address("2001:db8:1:2::"))
    assert not ssrf_guard.address_is_public(ipaddress.ip_address("::ffff:127.0.0.1"))
    assert ssrf_guard.address_is_public(ipaddress.ip_address("2606:4700:4700::1111"))


def test_public_ip_literals_pass_without_dns():
    ssrf_guard.ensure_public_url("https://8.8.8.8/robots.txt")
    ssrf_guard.ensure_public_url("https://1.1.1.1/paper.pdf")


def test_domain_resolving_to_loopback_is_refused(monkeypatch):
    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo",
                        lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 0))])
    with pytest.raises(ValueError):
        ssrf_guard.ensure_public_url("http://evil.example.com/a.pdf")


def test_dns_failure_is_refused_not_forgiven(monkeypatch):
    def boom(*a, **kw):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", boom)
    with pytest.raises(ValueError):
        ssrf_guard.ensure_public_url("http://nowhere.example/x")


def test_no_empty_addresses_after_resolve(monkeypatch):
    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", lambda *a, **kw: [])
    with pytest.raises(ValueError):
        ssrf_guard.ensure_public_url("http://empty.example/x")
