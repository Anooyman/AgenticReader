"""原 /memory 页退役的回归断言。

/memory 的页面职责已并进 /briefs（重管线 /load + 轻量入库 /light-load），
本测试钉住三件不该再变化的事：
1. 老书签打 /memory 必须 302 到 /briefs——不是 404，也不是 200 空页；
2. 跟随重定向后最终落在 /briefs，拿到的仍是可渲染的简报页；
3. /api/v1/llmmemory/* 这条透明代理面随页面一起删除（本地 driver 实装后
   不需要第二套存储入口，留着它只会绕开 gateway 的作用域语义）。

全程不联网、不起真实服务：用 TestClient 直接打 pages 路由。
"""
import importlib.util

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ui.backend.api import pages


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(pages.router)
    return TestClient(app)


def test_memory_page_redirects_to_briefs():
    resp = _client().get("/memory", follow_redirects=False)
    assert resp.status_code == 302, "/memory 应保留 302（老书签不能变 404）"
    assert resp.headers["location"] == "/briefs"


def test_memory_page_not_followed_as_own_page():
    """跟随重定向后拿到的应是 /briefs 的渲染结果，而不是另一个 memory 页面。"""
    resp = _client().get("/memory", follow_redirects=True)
    assert resp.status_code == 200
    assert resp.url.path != "/memory"


def test_llmmemory_proxy_module_is_gone():
    """/api/v1/llmmemory/* 透明代理模块应随页面退役一起消失。"""
    assert importlib.util.find_spec("src.ui.backend.api.v1.llmmemory") is None


def test_briefs_page_still_served():
    resp = _client().get("/briefs")
    assert resp.status_code == 200
