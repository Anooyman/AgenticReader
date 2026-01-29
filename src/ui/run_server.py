"""启动脚本"""

import uvicorn
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if __name__ == "__main__":
    print("🚀 启动 AgenticReader 服务器...")
    print("📁 访问: http://localhost:8000")
    print("📚 API 文档: http://localhost:8000/docs")
    print()

    uvicorn.run(
        "src.ui.backend.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=["*.pyc", "__pycache__", ".venv/*", ".git/*", "*.egg-info"],
        log_level="info"
    )
