"""
Reader 并行处理模块

提供与文档阅读器相关的并行处理功能，用于加速章节处理、摘要生成等耗时操作。
"""

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Tuple

from src.utils.async_utils import parallel_process_with_filter

# IndexingRole / CommonRole 仅作为函数参数的默认值使用，为缩短本模块被导入时的
# 依赖链（agents prompts 模块较重），改为函数体内延迟导入。
# 请勿在模块级恢复这两条 import。

logger = logging.getLogger(__name__)


def _drop_llm_session(llm_client: Any, session_id: str) -> None:
    """
    一次性 LLM 调用结束后回收该 session 的消息历史。

    与 memory/llm_condense.py 的 message_histories.pop 先例一致：这些调用
    在语义上都是独立的一次性请求（不是多轮对话），调用结束即删除条目，
    既保证章节之间零历史共享，也防止 message_histories 字典无限增长。
    """
    histories = getattr(llm_client, "message_histories", None)
    if histories is None:
        return
    try:
        histories.pop(session_id, None)
    except Exception as e:
        logger.warning(f"回收会话 {session_id} 失败: {e}")


class ChapterProcessor:
    """
    章节并行处理器
    
    封装章节处理的常见并行操作模式，与 ReaderBase 配合使用。
    """
    
    def __init__(self, llm_client: Any, max_concurrent: int = 5):
        """
        初始化章节处理器
        
        Args:
            llm_client: LLM客户端实例（需要有 async_call_llm_chain 方法）
            max_concurrent: 最大并发数
        """
        self.llm_client = llm_client
        self.max_concurrent = max_concurrent
    
    async def process_chapters_summary_and_refactor(
        self,
        agenda_data_list: List[Dict[str, Any]],
        summary_role: Any = None,
        refactor_role: Any = None
    ) -> List[Tuple[str, str, str, Any, Any]]:
        """
        并行处理章节的总结和重构
        
        对每个章节：
        1. 并行执行 summary 和 refactor 两个 LLM 调用
        2. 多个章节之间也是并行处理
        
        Args:
            agenda_data_list: 章节数据列表，每个包含 title, data, pages
            summary_role: 总结角色配置
            refactor_role: 重构角色配置
            
        Returns:
            List[Tuple[title, summary, refactor_content, pages, data]]
        """
        # 默认值延迟求值：避免模块级依赖 agents prompts
        if summary_role is None:
            from src.agents.indexing.prompts import IndexingRole
            summary_role = IndexingRole.CONTENT_SUMMARY
        if refactor_role is None:
            from src.agents.common.prompts import CommonRole
            refactor_role = CommonRole.CONTENT_MERGE

        async def process_single_chapter(chapter_index: int, agenda_data: Dict[str, Any]) -> Tuple[str, str, str, Any, Any]:
            import time
            title = agenda_data.get("title")
            data = agenda_data.get("data")
            pages = agenda_data.get("pages")

            logger.info(f"🚀 [并发章节] 开始处理章节: {title} - {time.strftime('%H:%M:%S.%f')[:-3]}")

            content_values = list(data.values()) if isinstance(data, dict) else data

            # 并行执行总结和重构
            summary_prompt = f"请总结{title}的内容，上下文如下：{content_values}"
            refactor_prompt = f"请重新整理Content中的内容。\n\n Content：{content_values}"

            logger.info(f"📡 [并发章节] 发送2个并行请求 (summary + refactor) - {title} - {time.strftime('%H:%M:%S.%f')[:-3]}")

            # 每个调用使用唯一的 session_id（章节索引 + uuid 后缀），避免固定
            # "summary"/"refactor" 两个 session 被所有章节共享导致跨章节历史
            # 互相污染，且在超过 DEFAULT 上限后被静默截断
            summary_session = f"summary_{chapter_index}_{uuid.uuid4().hex[:8]}"
            refactor_session = f"refactor_{chapter_index}_{uuid.uuid4().hex[:8]}"

            async def call_and_cleanup(role: Any, prompt: str, session_id: str):
                try:
                    return await self.llm_client.async_call_llm_chain(
                        role, prompt, session_id, enable_llm_summary=False
                    )
                finally:
                    # 一次性调用，结束后立即回收 session，防止历史累积/字典膨胀
                    _drop_llm_session(self.llm_client, session_id)

            summary, refactor_content = await asyncio.gather(
                call_and_cleanup(summary_role, summary_prompt, summary_session),
                call_and_cleanup(refactor_role, refactor_prompt, refactor_session)
            )

            logger.info(f"✅ [并发章节] 章节处理完成: {title} - {time.strftime('%H:%M:%S.%f')[:-3]}")
            return title, summary or "", refactor_content or "", pages, data

        import time
        logger.info(f"🚀 ========== 开始并行处理 {len(agenda_data_list)} 个章节 ==========")
        logger.info(f"⚙️  并发配置: 最大并发数 = {self.max_concurrent}")
        logger.info(f"⏰ 启动时间: {time.strftime('%H:%M:%S.%f')[:-3]}")

        results = await parallel_process_with_filter(
            list(enumerate(agenda_data_list)),
            lambda pair: process_single_chapter(pair[0], pair[1]),
            self.max_concurrent
        )

        return results
    
    async def process_detail_summaries(
        self,
        chapters: List[Dict[str, Any]],
        answer_role: Any = None
    ) -> List[Tuple[str, str]]:
        """
        并行生成详细摘要
        
        Args:
            chapters: 章节数据列表，每个包含 title, context_data, query
            answer_role: 回答角色配置
            
        Returns:
            List[Tuple[title, answer]]
        """
        # 默认值延迟求值：避免模块级依赖 agents prompts
        if answer_role is None:
            from src.agents.common.prompts import CommonRole
            answer_role = CommonRole.CONTEXT_QA

        async def process_single_summary(chapter_index: int, chapter_data: Dict[str, Any]) -> Tuple[str, str]:
            title = chapter_data['title']
            context_data = chapter_data['context_data']
            query = chapter_data['query']
            
            logger.info(f"并行处理详细摘要: {title}")
            
            input_prompt = (
                f"请结合检索回来的上下文信息(Context data)回答客户问题\n\n"
                f"===== \n\nQuestion: {query}\n\n"
                f"===== \n\nContext data: {context_data}"
            )
            
            # 每次调用唯一 session_id 并在结束后回收：原先固定 "answer" 会与
            # PDF 聊天会话共用同一历史，造成并发调用间互相污染
            session_id = f"detail_{chapter_index}_{uuid.uuid4().hex[:8]}"
            try:
                answer = await self.llm_client.async_call_llm_chain(
                    answer_role, input_prompt, session_id
                )
                return (title, answer if answer and answer.strip() else "")
            except Exception as e:
                logger.error(f"生成标题 '{title}' 的摘要时出错: {e}")
                return (title, "")
            finally:
                _drop_llm_session(self.llm_client, session_id)
        
        results = await parallel_process_with_filter(
            list(enumerate(chapters)),
            lambda pair: process_single_summary(pair[0], pair[1]),
            self.max_concurrent
        )
        
        return results


class PageExtractor:
    """
    PDF页面并行提取器
    
    封装PDF页面图片内容的并行提取操作。
    """
    
    def __init__(self, llm_client: Any, extract_prompt: str, max_concurrent: int = 5):
        """
        初始化页面提取器
        
        Args:
            llm_client: LLM客户端实例（需要有 chat_model.invoke 方法）
            extract_prompt: 图片内容提取的提示词
            max_concurrent: 最大并发数
        """
        self.llm_client = llm_client
        self.extract_prompt = extract_prompt
        self.max_concurrent = max_concurrent
    
    async def extract_pages_parallel(
        self,
        image_paths: List[str]
    ) -> List[Dict[str, Any]]:
        """
        并行提取多页图片内容
        
        Args:
            image_paths: 图片路径列表（已按页码排序）
            
        Returns:
            提取结果列表（按页码排序），每个元素包含 {"data": str, "page": str}
        """
        import base64
        import re
        from langchain_core.messages import HumanMessage
        
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def extract_single_page(idx: int, path: str) -> Dict[str, Any]:
            """提取单页内容"""
            import time
            async with semaphore:
                encoded_image = None
                try:
                    # 提取页码用于日志
                    match = re.search(r'page_(\d+)\.png', path)
                    page_num = match.group(1) if match else str(idx + 1)

                    logger.info(f"🚀 [并发] 开始处理页面 {page_num} (索引 {idx}) - {time.strftime('%H:%M:%S.%f')[:-3]}")

                    # 读取并编码图片文件
                    with open(path, 'rb') as img_file:
                        img_data = img_file.read()
                        encoded_image = base64.b64encode(img_data).decode('ascii')
                        del img_data

                    # 构建LLM消息
                    message = [HumanMessage(
                        content=[
                            {
                                "type": "text",
                                "text": self.extract_prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}
                            },
                        ],
                    )]

                    logger.info(f"📡 [并发] 发送API请求 - 页面 {page_num} - {time.strftime('%H:%M:%S.%f')[:-3]}")

                    # 异步调用LLM处理
                    # 使用 ainvoke 异步方法（LangChain原生支持）
                    response = await self.llm_client.chat_model.ainvoke(message)

                    logger.info(f"✅ [并发] 收到响应 - 页面 {page_num} - {time.strftime('%H:%M:%S.%f')[:-3]}")

                    if not response or not response.content:
                        logger.warning(f"页面 {page_num} LLM返回空内容")
                        return None

                    return {
                        "data": response.content,
                        "page": page_num,
                        "_idx": idx  # 用于排序
                    }

                except FileNotFoundError:
                    logger.error(f"图片文件不存在: {path}")
                    return None
                except MemoryError:
                    logger.error(f"处理图片时内存不足: {path}")
                    import gc
                    gc.collect()
                    return None
                except Exception as e:
                    logger.error(f"处理图片 {path} 时发生错误: {e}")
                    return None
                finally:
                    if encoded_image is not None:
                        del encoded_image

        # 创建所有任务
        tasks = [extract_single_page(idx, path) for idx, path in enumerate(image_paths)]

        import time
        logger.info(f"🚀 ========== 开始并行提取 {len(tasks)} 页内容 ==========")
        logger.info(f"⚙️  并发配置: 最大并发数 = {self.max_concurrent}")
        logger.info(f"⏰ 启动时间: {time.strftime('%H:%M:%S.%f')[:-3]}")

        # 并行执行所有任务
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        results = []
        for result in all_results:
            if isinstance(result, Exception):
                logger.error(f"任务执行异常: {result}")
            elif result is not None:
                results.append(result)
        
        # 按原始顺序排序
        results.sort(key=lambda x: x.get('_idx', 0))
        
        # 移除临时排序字段
        for r in results:
            r.pop('_idx', None)
        
        logger.info(f"✅ 并行提取完成: 成功 {len(results)} 页, 失败 {len(image_paths) - len(results)} 页")
        
        return results
