"""聊天服务"""

from typing import Optional, Dict, Any
from datetime import datetime
from src.agents.answer import AnswerAgent
from .session_manager import SessionManager
from ..api.v1.config import load_config


class ChatService:
    """聊天服务单例"""

    def __init__(self):
        self.answer_agent: Optional[AnswerAgent] = None
        self.mode: Optional[str] = None
        self.doc_name: Optional[str] = None
        self.selected_docs: Optional[list] = None  # For manual mode
        self.session_manager = SessionManager()
        self.current_session: Optional[Dict] = None

    def initialize(
        self,
        mode: str,
        doc_name: Optional[str] = None,
        selected_docs: Optional[list] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        初始化聊天服务

        Args:
            mode: 聊天模式 (single/cross/manual)
            doc_name: 文档名称（single 模式必需）
            selected_docs: 选中的文档列表（manual 模式必需）
            session_id: 会话ID（可选，用于加载历史会话）

        Returns:
            包含初始化结果和会话信息的字典
        """
        try:
            print(f"🔧 初始化聊天服务: mode={mode}, doc_name={doc_name}, selected_docs={selected_docs}, session_id={session_id}")

            self.mode = mode
            self.doc_name = doc_name
            self.selected_docs = selected_docs

            # 会话管理逻辑
            if session_id:
                # 加载指定的历史会话
                self.current_session = self.session_manager.load_session(session_id, mode)
                if not self.current_session:
                    print(f"❌ 会话不存在: {session_id}")
                    return {"success": False, "error": "会话不存在"}

                # 从会话中恢复信息
                self.doc_name = self.current_session.get("doc_name")
                self.selected_docs = self.current_session.get("selected_docs")
                print(f"✅ 加载历史会话: {session_id}")

            else:
                # 创建新会话
                if mode == "single":
                    # Single 模式：自动加载或创建会话
                    if not doc_name:
                        print("❌ 单文档模式需要提供 doc_name")
                        return {"success": False, "error": "单文档模式需要提供 doc_name"}
                    self.current_session = self.session_manager.create_or_load_single_session(doc_name)
                else:
                    # Cross/Manual 模式：创建新会话
                    self.current_session = self.session_manager.create_session(
                        mode=mode,
                        doc_name=doc_name,
                        selected_docs=selected_docs
                    )
                print(f"✅ 创建/加载会话: {self.current_session['session_id']}")

            # 创建 AnswerAgent
            # 从配置中获取 provider
            config = load_config()
            provider = config.get("provider", "openai")
            print(f"📌 使用 LLM Provider: {provider}")
            
            if mode == "single":
                if not self.doc_name:
                    print("❌ 单文档模式需要提供 doc_name")
                    return {"success": False, "error": "单文档模式需要提供 doc_name"}
                self.answer_agent = AnswerAgent(doc_name=self.doc_name, provider=provider)
            elif mode == "cross":
                # 跨文档智能对话模式（自动选择相关文档）
                self.answer_agent = AnswerAgent(doc_name=None, provider=provider)
            elif mode == "manual":
                # 跨文档手动选择模式（手动指定多个文档）
                if not self.selected_docs or len(self.selected_docs) == 0:
                    print("❌ 手动选择模式需要提供 selected_docs")
                    return {"success": False, "error": "手动选择模式需要提供 selected_docs"}
                self.answer_agent = AnswerAgent(doc_name=None, provider=provider)
                # Validate selected documents
                valid_docs, invalid_docs = self.answer_agent.validate_manual_selected_docs(self.selected_docs)
                if invalid_docs:
                    print(f"⚠️  以下文档未找到或未索引: {invalid_docs}")
                if len(valid_docs) == 0:
                    print("❌ 没有有效的文档可以使用")
                    return {"success": False, "error": "没有有效的文档可以使用"}
                self.selected_docs = valid_docs
                print(f"✅ 有效文档数: {len(valid_docs)}")
            else:
                print(f"❌ 不支持的模式: {mode}")
                return {"success": False, "error": f"不支持的模式: {mode}"}

            # 加载历史消息到 LLM（如果有）
            if self.current_session and self.current_session.get("message_count", 0) > 0:
                llm_history = self.session_manager.get_session_history_for_llm(self.current_session)
                # 将历史加载到 AnswerAgent 的 LLM 中
                # 传递 selected_docs 以便为跨文档模式设置 conversation_turns
                if hasattr(self.answer_agent, 'load_history'):
                    self.answer_agent.load_history(llm_history, selected_docs=self.selected_docs)
                print(f"✅ 加载历史消息: {len(llm_history)} 条")

            print(f"✅ 聊天服务初始化成功")

            # 返回完整的会话信息
            return {
                "success": True,
                "session_id": self.current_session["session_id"],
                "mode": self.current_session["mode"],
                "doc_name": self.current_session.get("doc_name"),
                "selected_docs": self.current_session.get("selected_docs"),
                "title": self.current_session["title"],
                "message_count": self.current_session["message_count"],
                "messages": self.current_session.get("messages", [])
            }

        except Exception as e:
            print(f"❌ 聊天服务初始化失败: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def chat(self, user_query: str) -> Dict[str, Any]:
        """处理聊天消息"""
        try:
            if not self.answer_agent:
                return {
                    "answer": "聊天服务未初始化，请先初始化。",
                    "references": []
                }

            if not self.current_session:
                return {
                    "answer": "会话未初始化，请先初始化。",
                    "references": []
                }

            # 保存用户消息
            self.session_manager.save_message(
                session_id=self.current_session["session_id"],
                mode=self.mode,
                role="user",
                content=user_query,
                doc_name=self.doc_name
            )

            # 根据模式调用 AnswerAgent
            if self.mode == "manual":
                # 手动选择模式：传入手动选择的文档列表
                result = await self.answer_agent.graph.ainvoke({
                    "user_query": user_query,
                    "current_doc": None,
                    "manual_selected_docs": self.selected_docs,
                    "needs_retrieval": True,
                    "is_complete": False
                })
            else:
                # 其他模式（single, cross, general）
                result = await self.answer_agent.graph.ainvoke({
                    "user_query": user_query,
                    "current_doc": self.doc_name,
                    "needs_retrieval": False,
                    "is_complete": False
                })

            final_answer = result.get("final_answer", "")
            selected_documents = result.get("selected_documents", [])
            multi_doc_results = result.get("multi_doc_results", {})

            # 转换为前端需要的格式
            references = []

            # Cross模式：显示自动选择的文档
            if self.mode == "cross" and selected_documents:
                for doc in selected_documents:
                    references.append({
                        "doc_name": doc.get("doc_name", ""),
                        "similarity_score": doc.get("similarity_score", 0.0)
                    })

            # Manual模式：显示检索到的文档
            if self.mode == "manual" and multi_doc_results:
                for doc_name in multi_doc_results.keys():
                    references.append({
                        "doc_name": doc_name,
                        "similarity_score": None
                    })

            # 保存助手回复
            self.session_manager.save_message(
                session_id=self.current_session["session_id"],
                mode=self.mode,
                role="assistant",
                content=final_answer,
                references=references,
                doc_name=self.doc_name
            )

            # 更新 current_session（刷新消息计数等）
            self.current_session = self.session_manager.load_session(
                self.current_session["session_id"],
                self.mode
            )

            return {
                "answer": final_answer,
                "references": references,
                "mode": self.mode
            }

        except Exception as e:
            print(f"❌ 聊天处理失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "answer": f"处理失败: {str(e)}",
                "references": []
            }

    def reset(self):
        """重置聊天服务（清空当前会话的消息，保持会话连接）"""
        if not self.current_session:
            print("⚠️ 没有活跃的会话，无需重置")
            return

        session_id = self.current_session.get("session_id")
        mode = self.current_session.get("mode")

        # 1. 清空内存中的历史记录
        if self.answer_agent and hasattr(self.answer_agent, 'reset_history'):
            self.answer_agent.reset_history()

        # 2. 清空session文件中的消息
        session = self.session_manager.load_session(session_id, mode)
        if session:
            session["messages"] = []
            session["message_count"] = 0
            session["updated_at"] = datetime.now().isoformat()

            # 保存到文件
            from pathlib import Path
            session_dir = self.session_manager._get_session_dir(mode)

            # 确定文件名
            if mode == "single":
                filename = session.get("doc_name", session_id)
            else:
                filename = session_id

            session_path = session_dir / f"{filename}.json"
            self.session_manager._save_session_file(session_path, session)
            print(f"✅ 已清空session文件: {session_path}")

            # 更新内存中的 current_session（重要！否则前端会读到旧数据）
            self.current_session = session
            print(f"✅ 已更新内存中的 current_session")
        else:
            print(f"⚠️ 无法加载会话文件（mode={mode}, session_id={session_id}），跳过文件清空")
            # 即使文件加载失败，也要清空内存中的 current_session 消息
            if self.current_session:
                self.current_session["messages"] = []
                self.current_session["message_count"] = 0
                self.current_session["updated_at"] = datetime.now().isoformat()
                print(f"✅ 已清空内存中的 current_session（文件未找到）")

        # 3. 重新实例化AnswerAgent（这会重新创建所有retrieval agents）
        from src.agents.answer import AnswerAgent

        if self.mode == "single" and self.doc_name:
            self.answer_agent = AnswerAgent(doc_name=self.doc_name)
            print(f"✅ 重新实例化 AnswerAgent (single模式, 文档: {self.doc_name})")
        elif self.mode == "cross":
            self.answer_agent = AnswerAgent()
            print(f"✅ 重新实例化 AnswerAgent (cross模式)")
        elif self.mode == "manual" and self.selected_docs:
            self.answer_agent = AnswerAgent()
            print(f"✅ 重新实例化 AnswerAgent (manual模式, {len(self.selected_docs)}个文档)")

        print("✅ 聊天服务已完全重置（包括文件和retrieval agents）")

    def get_current_session(self) -> Optional[Dict]:
        """获取当前会话信息"""
        return self.current_session

    def list_sessions(self, mode: str, limit: Optional[int] = None) -> list:
        """列出指定模式的会话列表"""
        return self.session_manager.list_sessions(mode, limit)

    def delete_session(self, session_id: str, mode: str):
        """删除指定会话"""
        self.session_manager.delete_session(session_id, mode)
        # 如果删除的是当前会话，清空当前状态
        if self.current_session and self.current_session["session_id"] == session_id:
            self.current_session = None
            self.answer_agent = None
            self.mode = None
            self.doc_name = None
            self.selected_docs = None


# 全局单例
chat_service = ChatService()
