"""章节信息 API"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import json
from pathlib import Path

from ...config import JSON_DATA_DIR, VECTOR_DB_DIR, DATA_DIR

router = APIRouter()


@router.get("/documents/{doc_name}/chapters")
async def get_chapters(doc_name: str) -> Dict[str, Any]:
    """获取文档章节信息"""
    try:
        # 尝试从 structure.json 读取
        structure_path = JSON_DATA_DIR / doc_name / "structure.json"

        if structure_path.exists():
            with open(structure_path, 'r', encoding='utf-8') as f:
                structure_data = json.load(f)

            agenda_dict = structure_data.get("agenda_dict", {})
            chapters = []

            for title, pages in agenda_dict.items():
                if not pages:
                    continue

                unique_pages = sorted(set(int(p) for p in pages if isinstance(p, (int, float, str))))
                if not unique_pages:
                    continue

                chapters.append({
                    "title": title,
                    "pages": unique_pages,
                    "start_page": min(unique_pages),
                    "end_page": max(unique_pages),
                    "page_count": len(unique_pages)
                })

            return {
                "success": True,
                "doc_name": doc_name,
                "total_chapters": len(chapters),
                "chapters": sorted(chapters, key=lambda x: x['start_page'])
            }

        # 如果没有章节信息，返回空列表
        return {
            "success": True,
            "doc_name": doc_name,
            "total_chapters": 0,
            "chapters": []
        }

    except Exception as e:
        print(f"❌ 获取章节信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
