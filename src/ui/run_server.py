#!/usr/bin/env python3
"""
LLMReader POC UI 重构版服务器启动脚本
"""

import uvicorn
from pathlib import Path

def main():
    """启动重构后的服务器"""
    print("🚀 启动 LLMReader POC UI 重构版服务器...")

    # 项目信息
    project_root = Path(__file__).resolve().parents[2]
    print(f"📁 项目根目录: {project_root}")
    print(f"🌐 服务器地址: http://localhost:8000")
    print(f"📚 API文档: http://localhost:8000/docs")
    print(f"💬 WebSocket聊天: ws://localhost:8000/ws/chat")
    print()
    print("按 Ctrl+C 停止服务器")

    # 启动服务器
    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
        app_dir=str(Path(__file__).parent)
    )

if __name__ == "__main__":
    main()