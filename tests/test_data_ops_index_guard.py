"""`POST /api/v1/data/documents/{filename}/index` 的文件名必须过 safe_path。

documents.py 的同类入口先 `safe_path(PDF_DIR, name)` 再拼路径，data_ops 这半
此前是 `PDF_DIR / filename` 裸拼——守卫的"统一"不该依赖 Starlette 单段路由
碰巧不匹配斜杠，换个挂载方式就退化了。这条钉的是 400 拒绝先于文件系统
探测发生。
"""
import pytest
from fastapi import HTTPException

from src.ui.backend.api.v1 import data_ops


@pytest.mark.parametrize("evil", ["../../../etc/passwd", "/abs/path.pdf", "..%2f..x"])
async def test_malicious_names_are_rejected_before_any_fs_probe(evil):
    with pytest.raises(HTTPException) as exc:
        await data_ops.index_pdf(evil, background_tasks=None)
    assert exc.value.status_code == 400
