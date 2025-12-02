"""
Reader 并行处理模块

提供与文档阅读器相关的并行处理功能，用于加速章节处理、摘要生成等耗时操作。
"""

import asyncio
import logging
from typing import Any, Dict, List, Tuple

from src.utils.async_utils import run_async, parallel_process_with_filter
from src.config.prompts.reader_prompts import ReaderRole

logger = logging.getLogger(__name__)


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
        summary_role: Any = ReaderRole.SUMMARY,
        refactor_role: Any = ReaderRole.REFACTOR
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
        async def process_single_chapter(agenda_data: Dict[str, Any]) -> Tuple[str, str, str, Any, Any]:
            title = agenda_data.get("title")
            data = agenda_data.get("data")
            pages = agenda_data.get("pages")
            
            content_values = list(data.values()) if isinstance(data, dict) else data
            
            # 并行执行总结和重构
            summary_prompt = f"请总结{title}的内容，上下文如下：{content_values}"
            refactor_prompt = f"请重新整理Content中的内容。\n\n Content：{content_values}"
            
            summary, refactor_content = await asyncio.gather(
                self.llm_client.async_call_llm_chain(summary_role, summary_prompt, "summary"),
                self.llm_client.async_call_llm_chain(refactor_role, refactor_prompt, "refactor")
            )
            
            logger.info(f"章节 '{title}' 处理完成")
            return title, summary or "", refactor_content or "", pages, data
        
        results = await parallel_process_with_filter(
            agenda_data_list,
            process_single_chapter,
            self.max_concurrent
        )
        
        return results
    
    async def process_detail_summaries(
        self,
        chapters: List[Dict[str, Any]],
        answer_role: Any = ReaderRole.ANSWER
    ) -> List[Tuple[str, str]]:
        """
        并行生成详细摘要
        
        Args:
            chapters: 章节数据列表，每个包含 title, context_data, query
            answer_role: 回答角色配置
            
        Returns:
            List[Tuple[title, answer]]
        """
        async def process_single_summary(chapter_data: Dict[str, Any]) -> Tuple[str, str]:
            title = chapter_data['title']
            context_data = chapter_data['context_data']
            query = chapter_data['query']
            
            logger.info(f"并行处理详细摘要: {title}")
            
            input_prompt = (
                f"请结合检索回来的上下文信息(Context data)回答客户问题\n\n"
                f"===== \n\nQuestion: {query}\n\n"
                f"===== \n\nContext data: {context_data}"
            )
            
            try:
                answer = await self.llm_client.async_call_llm_chain(
                    answer_role, input_prompt, "answer"
                )
                return (title, answer if answer and answer.strip() else "")
            except Exception as e:
                logger.error(f"生成标题 '{title}' 的摘要时出错: {e}")
                return (title, "")
        
        results = await parallel_process_with_filter(
            chapters,
            process_single_summary,
            self.max_concurrent
        )
        
        return results


def run_parallel_chapter_processing(
    llm_client: Any,
    agenda_data_list: List[Dict[str, Any]],
    summary_role: Any = ReaderRole.SUMMARY,
    refactor_role: Any = ReaderRole.REFACTOR,
    max_concurrent: int = 5
) -> List[Tuple[str, str, str, Any, Any]]:
    """
    同步接口：并行处理章节的总结和重构
    
    这是一个便捷的同步包装函数，内部使用异步并行处理。
    
    Args:
        llm_client: LLM客户端实例（需要有 async_call_llm_chain 方法）
        agenda_data_list: 章节数据列表，每个包含:
            - title: 章节标题
            - data: 章节数据字典 {page: content}
            - pages: 页码列表
        summary_role: 总结角色配置
        refactor_role: 重构角色配置
        max_concurrent: 最大并发数（默认5，避免API限流）
        
    Returns:
        List[Tuple[title, summary, refactor_content, pages, data]]
        
    Example:
        results = run_parallel_chapter_processing(
            llm_client=pdf_reader,
            agenda_data_list=agenda_data_list,
            max_concurrent=5
        )
        for title, summary, refactor, pages, data in results:
            # 处理结果...
    """
    processor = ChapterProcessor(llm_client, max_concurrent)
    
    return run_async(
        processor.process_chapters_summary_and_refactor(
            agenda_data_list, summary_role, refactor_role
        )
    )


def run_parallel_detail_summaries(
    llm_client: Any,
    chapters: List[Dict[str, Any]],
    answer_role: Any = ReaderRole.ANSWER,
    max_concurrent: int = 5
) -> List[Tuple[str, str]]:
    """
    同步接口：并行生成详细摘要
    
    这是一个便捷的同步包装函数，内部使用异步并行处理。
    
    Args:
        llm_client: LLM客户端实例（需要有 async_call_llm_chain 方法）
        chapters: 章节数据列表，每个包含:
            - title: 章节标题
            - context_data: 上下文数据
            - query: 查询问题
        answer_role: 回答角色配置
        max_concurrent: 最大并发数（默认5，避免API限流）
        
    Returns:
        List[Tuple[title, answer]]
        
    Example:
        chapters = [
            {'title': '第一章', 'context_data': [...], 'query': '总结内容'},
            {'title': '第二章', 'context_data': [...], 'query': '总结内容'},
        ]
        results = run_parallel_detail_summaries(
            llm_client=pdf_reader,
            chapters=chapters,
            max_concurrent=5
        )
        for title, answer in results:
            # 处理结果...
    """
    processor = ChapterProcessor(llm_client, max_concurrent)
    
    return run_async(
        processor.process_detail_summaries(chapters, answer_role)
    )


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
            async with semaphore:
                encoded_image = None
                try:
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

                    # 异步调用LLM处理
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(
                        None, self.llm_client.chat_model.invoke, message
                    )

                    if not response or not response.content:
                        logger.warning(f"页面 {idx + 1} LLM返回空内容")
                        return None

                    # 提取页码
                    match = re.search(r'page_(\d+)\.png', path)
                    page_num = match.group(1) if match else str(idx + 1)

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
        
        logger.info(f"🚀 开始并行提取 {len(tasks)} 页内容 (最大并发: {self.max_concurrent})")
        
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


def run_parallel_page_extraction(
    llm_client: Any,
    image_paths: List[str],
    extract_prompt: str,
    max_concurrent: int = 5
) -> List[Dict[str, Any]]:
    """
    同步接口：并行提取PDF页面图片内容
    
    这是一个便捷的同步包装函数，内部使用异步并行处理。
    
    Args:
        llm_client: LLM客户端实例（需要有 chat_model.invoke 方法）
        image_paths: 图片路径列表（应已按页码排序）
        extract_prompt: 图片内容提取的提示词
        max_concurrent: 最大并发数（默认5，避免API限流）
        
    Returns:
        提取结果列表（按页码排序），每个元素包含 {"data": str, "page": str}
        
    Example:
        results = run_parallel_page_extraction(
            llm_client=pdf_reader,
            image_paths=sorted_image_paths,
            extract_prompt="请提取图片中的文字内容",
            max_concurrent=5
        )
        for item in results:
            print(f"Page {item['page']}: {item['data'][:100]}...")
    """
    extractor = PageExtractor(llm_client, extract_prompt, max_concurrent)
    
    return run_async(
        extractor.extract_pages_parallel(image_paths)
    )
