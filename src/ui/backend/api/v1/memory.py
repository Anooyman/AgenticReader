"""Memory 浏览/搜索/删除 REST API——供 /data 页面的 Memory tab 查看
src.memory 向量库的内容。改自 ai-research-pipeline 的 webapp/api/memory.py。

原实现的跨 venv subprocess 调用（memory_browse.py 的 fetch_* 函数）在
合并进 AgenticReader 后已经改为同进程直接调用（见 services/memory_browse.py
的说明），这里的路由/错误处理逻辑基本不变。
"""
from fastapi import APIRouter, HTTPException

from src.ui.backend.services import memory_browse

router = APIRouter()


@router.get("/overview")
async def get_overview():
    return await memory_browse.fetch_overview()


@router.get("/namespace/{namespace}")
async def get_namespace(namespace: str):
    return await memory_browse.fetch_namespace(namespace)


@router.get("/item/{memory_id}")
async def get_item(memory_id: str):
    data = await memory_browse.fetch_detail(memory_id)
    if not data.get("found"):
        raise HTTPException(status_code=404, detail="memory not found")
    return data


@router.delete("/item/{memory_id}")
async def delete_item(memory_id: str):
    return await memory_browse.delete_memory(memory_id)


@router.delete("/namespace/{namespace}/source/{source_id}")
async def delete_source(namespace: str, source_id: str):
    """删掉一个来源（一篇论文/一段对话）在该 namespace 下的全部记忆行——
    对应 UI 上"删除整组"按钮，一次删掉一张 group 卡片的所有 chunk。"""
    return await memory_browse.delete_source(namespace, source_id)


@router.delete("/namespace/{namespace}")
async def delete_namespace(namespace: str):
    """清空一个 namespace 下的全部记忆。"""
    return await memory_browse.delete_namespace(namespace)


@router.post("/search")
async def post_search(body: dict):
    """手动执行一次检索测试——复用 agentic_search，验证效果。"""
    query = (body or {}).get("query")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    namespace = (body or {}).get("namespace")

    from src.memory.search import agentic_search

    result = await agentic_search(query, namespace=[namespace] if namespace else None, provider="openai")
    return result
