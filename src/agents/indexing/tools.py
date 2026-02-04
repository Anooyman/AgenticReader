"""
IndexingAgent 工具方法实现

所有可复用的工具方法（*_impl）
"""

from typing import Dict, List, Any, Optional, TYPE_CHECKING
import logging
import json
import os
import re
from pathlib import Path

if TYPE_CHECKING:
    from .agent import IndexingAgent

logger = logging.getLogger(__name__)


class IndexingTools:
    """IndexingAgent 工具方法集合"""

    def __init__(self, agent: 'IndexingAgent'):
        """
        Args:
            agent: IndexingAgent实例（依赖注入）
        """
        self.agent = agent

    async def generate_summary_impl(
        self,
        context_data: Dict[str, Any],
        doc_name: str,
        session_id: str = "summary_generation"
    ) -> str:
        """
        生成文档简要摘要（工具方法）

        Args:
            context_data: 上下文数据（可以是全文内容或章节摘要字典）
            doc_name: 文档名称
            session_id: 会话ID，用于区分不同调用场景

        Returns:
            简要摘要文本
        """
        logger.info(f"📝 [Tool:generate_summary] 生成摘要: {doc_name}")

        try:
            from src.agents.common.prompts import CommonRole

            query = (
                "请按照文章本身的章节信息和叙事结构，整理这篇文章的主要内容，"
                "每个章节都需要有一定的简单介绍。如果背景知识中有一些文章的基本信息也需要一并总结。"
                "仅需要返回相关内容，多余的话无需返回。返回中文。"
            )

            # 构建输入 prompt（与 ReaderBase.get_answer 相同的格式）
            input_prompt = (
                f"请结合检索回来的上下文信息(Context data)回答客户问题\n\n"
                f"===== \n\nQuestion: {query}\n\n"
                f"===== \n\nContext data: {context_data}"
            )

            # 使用异步调用（禁用历史总结，摘要生成不需要保留上下文）
            answer = await self.agent.llm.async_call_llm_chain(
                CommonRole.CONTEXT_QA,
                input_prompt,
                session_id,
                enable_llm_summary=False
            )

            if not answer or not answer.strip():
                logger.warning("生成的简要摘要为空")
                return f"文档 {doc_name} 的简要摘要（生成失败）"

            logger.info(f"✅ [Tool:generate_summary] 摘要生成完成，长度: {len(answer)} 字符")
            return answer

        except Exception as e:
            logger.error(f"❌ [Tool:generate_summary] 生成摘要失败: {e}")
            return f"文档 {doc_name} 的简要摘要（生成错误: {str(e)}）"

    async def build_vector_index_impl(
        self,
        doc_name: str,
        chunks: List[Dict[str, str]],
        metadata: Optional[Dict] = None
    ) -> str:
        """
        构建向量索引（工具方法）

        Args:
            doc_name: 文档名称
            chunks: 文本分块列表，格式：[{"data": str, "page": str}, ...]
            metadata: 元数据（包含tags, summary等）

        Returns:
            索引路径
        """
        logger.info(f"🔨 [Tool:build_index] 构建向量索引: {doc_name}, 分块数: {len(chunks)}")

        try:
            from src.config.settings import DATA_ROOT
            from src.core.vector_db.vector_db_client import VectorDBClient
            from langchain.docstore.document import Document

            # 构建索引路径
            index_dir = Path(DATA_ROOT) / "vector_db" / f"{doc_name}_data_index"
            index_dir.mkdir(parents=True, exist_ok=True)
            index_path = str(index_dir)

            # 创建 VectorDBClient，直接使用 self.agent.embedding_model
            vector_db_client = VectorDBClient(index_path, embedding_model=self.agent.embedding_model)

            # 准备文档列表
            vector_db_docs = []

            # 提取元数据
            summary = metadata.get("summary", "") if metadata else ""

            # 为每个分块创建Document对象
            for i, chunk_item in enumerate(chunks):
                chunk_data = chunk_item.get("data", "")
                chunk_page = chunk_item.get("page", f"chunk_{i+1}")

                if not chunk_data or not chunk_data.strip():
                    continue

                # 创建内容文档
                doc = Document(
                    page_content=chunk_data,
                    metadata={
                        "type": "content",
                        "chunk_id": i,
                        "page": chunk_page,
                        "doc_name": doc_name,
                    }
                )
                vector_db_docs.append(doc)

            # 添加文档结构信息
            structure_doc = Document(
                page_content="Document Structure",
                metadata={
                    "type": "structure",
                    "doc_name": doc_name,
                    "total_chunks": len(chunks),
                    "summary": summary,
                }
            )
            vector_db_docs.append(structure_doc)

            # 构建向量数据库
            logger.info(f"开始构建向量数据库，共 {len(vector_db_docs)} 个文档...")
            vector_db_client.build_vector_db(vector_db_docs)

            logger.info(f"✅ [Tool:build_index] 索引构建完成: {index_path}")
            return index_path

        except Exception as e:
            logger.error(f"❌ [Tool:build_index] 索引构建失败: {e}")
            raise

    async def extract_pdf_data_impl(self, pdf_file_path: str) -> Dict[str, Any]:
        """
        将 PDF 转为图片并用 LLM 提取每页内容（工具方法）

        Args:
            pdf_file_path: PDF 文件名（不含路径和扩展名）

        Returns:
            提取结果字典:
            {
                "pdf_data_list": List[Dict],  # 每页提取的内容
                "image_paths": List[str],      # 图片文件路径列表
                "json_path": str,              # JSON数据文件路径
                "image_folder": str            # 图片文件夹路径
            }

        Raises:
            ValueError: 输入参数无效
            FileNotFoundError: PDF文件不存在
            Exception: 处理过程中的其他错误
        """
        from src.utils.helpers import pdf_to_images, read_images_in_directory
        from .prompts import IndexingRole, INDEXING_PROMPTS

        logger.info(f"📄 [Tool:extract_pdf] ========== 开始提取PDF内容 ==========")
        logger.info(f"📄 [Tool:extract_pdf] 输入文件名: {pdf_file_path}")

        # 输入验证
        if not pdf_file_path or not isinstance(pdf_file_path, str):
            raise ValueError("PDF文件路径不能为空且必须是字符串")

        # 构建路径
        output_folder_path = os.path.join(self.agent.pdf_image_path, pdf_file_path)
        pdf_path = os.path.join(self.agent.pdf_path, f"{pdf_file_path}.pdf")
        # JSON文件放在文档文件夹中
        doc_json_folder = os.path.join(self.agent.json_data_path, pdf_file_path)
        output_json_path = os.path.join(doc_json_folder, "data.json")

        logger.info(f"📄 [Tool:extract_pdf] 完整路径:")
        logger.info(f"📄 [Tool:extract_pdf]   - PDF: {pdf_path}")
        logger.info(f"📄 [Tool:extract_pdf]   - 图片文件夹: {output_folder_path}")
        logger.info(f"📄 [Tool:extract_pdf]   - JSON输出: {output_json_path}")

        # 验证PDF文件存在
        if not os.path.exists(pdf_path):
            logger.error(f"📄 [Tool:extract_pdf] ❌ PDF文件不存在: {pdf_path}")
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

        logger.info(f"📄 [Tool:extract_pdf] ✅ PDF文件存在")

        try:
            image_paths = []

            # 检查是否已有JSON数据
            if os.path.exists(output_json_path):
                logger.info(f"发现已存在的JSON数据: {output_json_path}")
                try:
                    with open(output_json_path, 'r', encoding='utf-8') as f:
                        image_content_list = json.load(f)

                    # 获取已存在的图片路径
                    if os.path.exists(output_folder_path):
                        image_paths = read_images_in_directory(output_folder_path)
                        # 排序图片路径
                        def safe_page_sort(path):
                            try:
                                match = re.search(r'page_(\d+)\.png', path)
                                return int(match.group(1)) if match else float('inf')
                            except:
                                return float('inf')
                        image_paths = sorted(image_paths, key=safe_page_sort)

                    logger.info(f"✅ [Tool:extract_pdf] 从缓存加载: {len(image_content_list)} 页")

                    return {
                        "pdf_data_list": image_content_list,
                        "image_paths": image_paths,
                        "json_path": output_json_path,
                        "image_folder": output_folder_path
                    }
                except Exception as e:
                    logger.warning(f"读取缓存JSON失败，将重新提取: {e}")

            # 转换PDF为图片
            logger.info(f"📄 [Tool:extract_pdf] 开始转换PDF为图片...")
            logger.info(f"📄 [Tool:extract_pdf]   - DPI: {self.agent.pdf_dpi}")
            logger.info(f"📄 [Tool:extract_pdf]   - 质量预设: {self.agent.pdf_quality}")
            conversion_stats = pdf_to_images(
                pdf_path, output_folder_path,
                dpi=self.agent.pdf_dpi, quality=self.agent.pdf_quality
            )
            logger.info(f"📄 [Tool:extract_pdf] ✅ PDF转图片完成: 成功 {conversion_stats['successful_pages']} 页")

            # 获取图片路径并排序
            image_paths = read_images_in_directory(output_folder_path)
            if not image_paths:
                logger.error("没有找到可处理的图片文件")
                return {
                    "pdf_data_list": [],
                    "image_paths": [],
                    "json_path": output_json_path,
                    "image_folder": output_folder_path
                }

            # 安全的页码排序
            def safe_page_sort(path):
                try:
                    match = re.search(r'page_(\d+)\.png', path)
                    return int(match.group(1)) if match else float('inf')
                except:
                    return float('inf')

            sorted_image_paths = sorted(image_paths, key=safe_page_sort)
            logger.info(f"找到 {len(sorted_image_paths)} 个图片文件待处理")

            # 使用并行处理提取图片内容
            extract_prompt = INDEXING_PROMPTS.get(
                IndexingRole.IMAGE_EXTRACT, "请提取图片中的文字内容"
            )
            logger.info(f"📄 [Tool:extract_pdf] 开始并行提取图片内容...")
            logger.info(f"📄 [Tool:extract_pdf]   - 图片数量: {len(sorted_image_paths)}")
            logger.info(f"📄 [Tool:extract_pdf]   - 最大并发: 5")
            logger.info(f"📄 [Tool:extract_pdf]   - 使用LLM: {self.agent.llm.provider}")

            # 直接使用异步方法（因为当前已经在async上下文中）
            from src.core.parallel import PageExtractor
            extractor = PageExtractor(self.agent.llm, extract_prompt, max_concurrent=5)
            image_content_list = await extractor.extract_pages_parallel(sorted_image_paths)

            logger.info(f"📄 [Tool:extract_pdf] ✅ 图片内容提取完成")

            # 保存提取结果到JSON文件
            if image_content_list:
                try:
                    # 确保目录存在
                    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)

                    with open(output_json_path, 'w', encoding='utf-8') as file:
                        json.dump(image_content_list, file, ensure_ascii=False, indent=2)

                    logger.info(f"数据已保存到: {output_json_path}")
                    logger.info(f"✅ [Tool:extract_pdf] 提取统计: 成功{len(image_content_list)}页")
                except Exception as e:
                    logger.error(f"保存JSON文件失败: {e}")
                    raise
            else:
                logger.error("没有成功提取任何页面内容")

            return {
                "pdf_data_list": image_content_list,
                "image_paths": sorted_image_paths,
                "json_path": output_json_path,
                "image_folder": output_folder_path
            }

        except Exception as e:
            logger.error(f"❌ [Tool:extract_pdf] PDF数据提取失败: {e}")
            raise

    def split_pdf_raw_data(self, pdf_raw_data: List[Any]) -> List[List[Any]]:
        """
        将 PDF 原始数据按照 chunk_count 进行切分

        Args:
            pdf_raw_data: PDF原始数据列表

        Returns:
            切分后的数据块列表
        """
        if not isinstance(pdf_raw_data, list):
            logger.error("pdf_raw_data 不是 list，无法切分")
            return []

        chunks = [
            pdf_raw_data[i:i + self.agent.chunk_count]
            for i in range(0, len(pdf_raw_data), self.agent.chunk_count)
        ]
        logger.info(f"已将 pdf_raw_data 切分为 {len(chunks)} 个块，每块最多 {self.agent.chunk_count} 条")
        return chunks

    async def extract_toc_from_pages_impl(
        self,
        pdf_data_list: List[Dict[str, str]],
        max_pages: int = 10
    ) -> tuple[Optional[Dict[str, List]], bool]:
        """
        从PDF前几页快速提取目录结构（工具方法）

        Args:
            pdf_data_list: PDF每页数据列表
            max_pages: 最多检查的页数

        Returns:
            (agenda_dict, has_toc): 目录字典和是否找到目录的标志
        """
        from src.utils.helpers import extract_data_from_LLM_res
        from .prompts import IndexingRole

        logger.info(f"📖 [Tool:extract_toc] 尝试从前 {max_pages} 页提取目录")

        try:
            # 合并前几页的内容
            toc_pages = pdf_data_list[:max_pages]
            combined_content = "\n\n".join([
                f"[Page {item.get('page', i+1)}]\n{item.get('data', '')}"
                for i, item in enumerate(toc_pages)
            ])

            # 构建提取目录的 prompt
            input_prompt = f"这里是文章的前 {len(toc_pages)} 页内容，请查找并提取目录结构: {combined_content}"

            # 调用 LLM 提取目录
            response = self.agent.llm.call_llm_chain(
                IndexingRole.CHAPTER_EXTRACT,
                input_prompt,
                "toc_extract"
            )

            if not response:
                logger.warning("LLM返回空响应，未找到目录")
                return None, False

            # 解析 LLM 返回的结果
            result = extract_data_from_LLM_res(response)

            if not result or not isinstance(result, list) or len(result) == 0:
                logger.info("未在前几页检测到目录结构")
                return None, False

            # 转换为 agenda_dict 格式: {title: [pages]}
            agenda_dict = {}
            for item in result:
                if isinstance(item, dict) and "title" in item and "pages" in item:
                    title = item["title"]
                    pages = item["pages"]
                    if isinstance(pages, list):
                        agenda_dict[title] = pages
                    else:
                        agenda_dict[title] = [pages]

            if agenda_dict:
                logger.info(f"✅ [Tool:extract_toc] 成功提取目录: {len(agenda_dict)} 个章节")
                return agenda_dict, True
            else:
                logger.info("解析结果为空，未找到有效目录")
                return None, False

        except Exception as e:
            logger.error(f"❌ [Tool:extract_toc] 提取目录失败: {e}")
            return None, False

    async def analyze_full_structure_impl(
        self,
        pdf_data_list: List[Dict[str, str]]
    ) -> Dict[str, List]:
        """
        分析整个PDF文档的结构（工具方法）

        当PDF没有明确目录时，遍历全文分析章节结构

        Args:
            pdf_data_list: PDF每页数据列表

        Returns:
            agenda_dict: 目录字典 {title: [pages]}
        """
        from src.utils.helpers import extract_data_from_LLM_res, group_data_by_sections_with_titles
        from .prompts import IndexingRole

        logger.info(f"🔍 [Tool:analyze_structure] 开始分析全文结构: {len(pdf_data_list)} 页")

        try:
            # 将PDF数据分块处理（避免单次处理过长）
            chunks = self.split_pdf_raw_data(pdf_data_list)

            all_agenda_list = []

            # 并行处理每个分块
            for i, chunk in enumerate(chunks):
                logger.info(f"处理分块 {i+1}/{len(chunks)}")

                # 合并分块内容
                chunk_content = "\n\n".join([
                    f"[Page {item.get('page', idx+1)}]\n{item.get('data', '')}"
                    for idx, item in enumerate(chunk)
                ])

                # 构建 prompt
                input_prompt = f"这里是文章的部分内容: {chunk_content}"

                # 调用 LLM 提取章节
                response = self.agent.llm.call_llm_chain(
                    IndexingRole.CHAPTER_EXTRACT,
                    input_prompt,
                    f"structure_extract_chunk"
                )

                if response:
                    result = extract_data_from_LLM_res(response)
                    if isinstance(result, list):
                        all_agenda_list.extend(result)

            # 转换为 agenda_dict
            _, agenda_list = group_data_by_sections_with_titles(all_agenda_list, pdf_data_list)

            # 将列表格式转换为字典格式
            agenda_dict = {
                item['title']: item['pages']
                for item in agenda_list
            }

            logger.info(f"✅ [Tool:analyze_structure] 结构分析完成: {len(agenda_dict)} 个章节")

            return agenda_dict

        except Exception as e:
            logger.error(f"❌ [Tool:analyze_structure] 结构分析失败: {e}")
            # 返回默认结构（整个文档作为一个章节）
            return {"全文": list(range(1, len(pdf_data_list) + 1))}

    # ==================== 批量处理和管理方法 ====================

    async def process_documents_batch(
        self,
        doc_list: List[Dict[str, Any]],
        max_concurrent: int = 3
    ) -> List[Dict[str, Any]]:
        """
        批量处理文档列表

        Args:
            doc_list: 文档列表，每个元素格式：
                {
                    "doc_name": str,
                    "doc_path": str,
                    "doc_type": "pdf" | "url"
                }
            max_concurrent: 最大并发处理数

        Returns:
            处理结果列表
        """
        import asyncio

        logger.info(f"📦 开始批量处理文档: 共 {len(doc_list)} 个文档")

        results = []

        # 分批处理避免过载
        for i in range(0, len(doc_list), max_concurrent):
            batch = doc_list[i:i + max_concurrent]
            logger.info(f"处理第 {i // max_concurrent + 1} 批: {len(batch)} 个文档")

            # 并发处理当前批次
            tasks = []
            for doc_info in batch:
                # 构建初始状态
                state = {
                    "doc_name": doc_info["doc_name"],
                    "doc_path": doc_info["doc_path"],
                    "doc_type": doc_info["doc_type"],
                    "status": "pending"
                }
                # 创建处理任务
                task = self.agent.graph.ainvoke(state)
                tasks.append(task)

            # 等待当前批次完成
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果
            for j, result in enumerate(batch_results):
                doc_name = batch[j]["doc_name"]
                if isinstance(result, Exception):
                    logger.error(f"❌ 文档处理失败: {doc_name}, 错误: {result}")
                    results.append({
                        "doc_name": doc_name,
                        "status": "error",
                        "error": str(result)
                    })
                else:
                    logger.info(f"✅ 文档处理完成: {doc_name}, 状态: {result.get('status')}")
                    results.append(result)

        logger.info(f"✅ 批量处理完成: 成功 {sum(1 for r in results if r.get('status') == 'completed')} 个, 失败 {sum(1 for r in results if r.get('status') == 'error')} 个")

        return results

    async def _prepare_rebuild_state(
        self,
        doc_name: str,
        doc_path: str
    ) -> Dict[str, Any]:
        """
        准备重建的初始状态

        1. 加载 data.json 和 structure.json
        2. 删除旧的生成文件（chunks, summaries, vector_db）
        3. 清理 DocumentRegistry 中的旧记录
        4. 构建初始状态字典

        Args:
            doc_name: 文档名称
            doc_path: 文档路径

        Returns:
            初始化的 IndexingState
        """
        logger.info(f"🔄 [Rebuild] ========== 准备重建环境 ==========")

        # 1. 验证文件存在
        doc_json_folder = os.path.join(self.agent.json_data_path, doc_name)
        structure_path = os.path.join(doc_json_folder, "structure.json")
        data_path = os.path.join(doc_json_folder, "data.json")

        if not os.path.exists(structure_path):
            raise FileNotFoundError(f"结构文件不存在: {structure_path}")

        if not os.path.exists(data_path):
            raise FileNotFoundError(f"数据文件不存在: {data_path}")

        # 2. 加载 structure
        logger.info(f"📥 [Rebuild] 加载 structure.json...")
        with open(structure_path, 'r', encoding='utf-8') as f:
            structure_data = json.load(f)

        if "agenda_dict" in structure_data:
            agenda_dict = structure_data["agenda_dict"]
            has_toc = structure_data.get("has_toc", False)
        else:
            agenda_dict = structure_data
            has_toc = True

        logger.info(f"   ✅ 加载完成: {len(agenda_dict)} 个章节")

        # 3. 加载 PDF 数据
        logger.info(f"📥 [Rebuild] 加载 data.json...")
        with open(data_path, 'r', encoding='utf-8') as f:
            pdf_data_list = json.load(f)

        json_data_dict = {
            str(item.get("page", i+1)): item.get("data", "")
            for i, item in enumerate(pdf_data_list)
        }

        raw_data = "\n\n".join([
            f"[Page {item.get('page', i+1)}]\n{item.get('data', '')}"
            for i, item in enumerate(pdf_data_list)
        ])

        logger.info(f"   ✅ 加载完成: {len(pdf_data_list)} 页")

        # 4. 删除旧的生成文件
        logger.info(f"🗑️  [Rebuild] 删除旧的生成文件...")
        chunks_path = os.path.join(doc_json_folder, "chunks.json")
        if os.path.exists(chunks_path):
            os.remove(chunks_path)
            logger.info(f"   ✅ 删除 chunks.json")

        # 删除旧的摘要文件
        from src.config.constants import PathConstants
        output_folder = os.path.join(PathConstants.OUTPUT_DIR, doc_name)
        if os.path.exists(output_folder):
            import shutil
            shutil.rmtree(output_folder)
            logger.info(f"   ✅ 删除输出文件夹: {output_folder}")

        # 删除旧的向量数据库
        vector_db_folder = os.path.join(PathConstants.VECTOR_DB_DIR, doc_name)
        if os.path.exists(vector_db_folder):
            import shutil
            shutil.rmtree(vector_db_folder)
            logger.info(f"   ✅ 删除向量数据库: {vector_db_folder}")

        # 5. 清理 DocumentRegistry 中的旧记录
        logger.info(f"🗑️  [Rebuild] 清理文档注册信息...")
        old_doc = self.agent.doc_registry.get_by_name(doc_name)
        if old_doc:
            # 保存基本信息，但清除所有生成文件的路径
            logger.info(f"   ℹ️  旧记录: {old_doc.get('status', 'unknown')} 状态")
            # 不删除整个记录，让 register 节点更新
        logger.info(f"   ✅ Registry 准备就绪")

        # 6. 构建初始状态
        state = {
            "doc_name": doc_name,
            "doc_path": doc_path,
            "doc_type": "pdf",
            "pdf_data_list": pdf_data_list,
            "json_data_dict": json_data_dict,
            "raw_data": raw_data,
            "agenda_dict": agenda_dict,
            "has_toc": has_toc,
            "status": "loaded",
            "is_complete": False,
            "generated_files": {
                "images": [],  # 保留已有的图片
                "json_data": data_path,
                "vector_db": "",
                "summaries": []
            },
            "stage_status": {},  # 不设置跳过标志，强制重建所有内容
            "agenda_data_list": []  # 初始化为空，强制重建
        }

        logger.info(f"✅ [Rebuild] 初始状态准备完成")
        return state

    async def rebuild_from_structure(
        self,
        doc_name: str,
        doc_path: str
    ) -> Dict[str, Any]:
        """
        基于已有的 structure.json 重建文档数据

        使用专门的重建子图执行重建流程

        保持不变的文件：
        - structure.json: 手动编辑的结构
        - data.json: PDF 原始数据
        - pdf_image/: PDF 图片文件

        重新生成的内容：
        - chunks.json: 基于新结构重建章节数据
        - 章节摘要: 重新生成所有章节的摘要和重构内容
        - 向量数据库: 完全重建 FAISS 索引
        - 简要摘要: 重新生成整体文档摘要
        - DocumentRegistry: 更新文档注册信息

        Args:
            doc_name: 文档名称
            doc_path: 文档路径

        Returns:
            重建结果字典
        """
        logger.info(f"🔄 [Rebuild] ========== 开始从 structure 全面重建 ==========")
        logger.info(f"🔄 [Rebuild] 文档: {doc_name}")
        logger.info(f"🔄 [Rebuild] 使用重建子图执行流程")

        try:
            # 1. 准备初始状态（加载文件、删除旧数据、清理registry）
            state = await self._prepare_rebuild_state(doc_name, doc_path)

            # 2. 使用重建子图执行
            logger.info(f"🔄 [Rebuild] 开始执行重建子图...")
            result_state = await self.agent.rebuild_graph.ainvoke(state)

            # 3. 验证重建结果
            doc_json_folder = os.path.join(self.agent.json_data_path, doc_name)
            chunks_path = os.path.join(doc_json_folder, "chunks.json")

            logger.info(f"✅ [Rebuild] 重建完成！")
            logger.info(f"   📊 章节数: {len(result_state.get('agenda_data_list', []))}")
            logger.info(f"   📁 生成文件: {len(result_state.get('generated_files', {}).get('summaries', []))} 个摘要")
            logger.info(f"   🔍 向量库: {result_state.get('generated_files', {}).get('vector_db', 'N/A')}")

            return {
                "success": True,
                "doc_name": doc_name,
                "total_chapters": len(result_state.get("agenda_data_list", [])),
                "status": "completed",
                "generated_files": result_state.get("generated_files", {}),
                "rebuilt": {
                    "chunks": os.path.exists(chunks_path),
                    "summaries": len(result_state.get("generated_files", {}).get("summaries", [])) > 0,
                    "vector_db": bool(result_state.get("generated_files", {}).get("vector_db")),
                    "brief_summary": result_state.get("brief_summary") is not None,
                    "registry": self.agent.doc_registry.get_by_name(doc_name) is not None
                }
            }

        except Exception as e:
            logger.error(f"❌ [Rebuild] 重建失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e)
            }
