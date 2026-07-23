"""
IndexingAgent Workflow节点方法

所有workflow节点的实现
"""

from __future__ import annotations
from typing import Dict, TYPE_CHECKING
import logging
import os
import json
from pathlib import Path

from .state import IndexingState

if TYPE_CHECKING:
    from .agent import IndexingAgent

logger = logging.getLogger(__name__)


class IndexingNodes:
    """IndexingAgent Workflow节点方法集合"""

    def __init__(self, agent: 'IndexingAgent'):
        """
        Args:
            agent: IndexingAgent实例（依赖注入）
        """
        self.agent = agent

    async def check_cache(self, state: IndexingState) -> IndexingState:
        """
        步骤0：检查所有阶段的缓存文件

        检查每个阶段的输出文件是否存在，设置跳过标志，并尝试加载已有数据
        """
        logger.info(f"🔍 [CheckCache] ========== 步骤0: 检查所有缓存文件 ==========")
        logger.info(f"🔍 [CheckCache] 文档名称: {state['doc_name']}")

        doc_name = state["doc_name"]
        doc_type = state.get("doc_type")

        # 初始化阶段状态字典
        stage_status = {
            "parse": {"skip": False, "files": []},
            "extract_structure": {"skip": False, "files": []},
            "chunk_text": {"skip": False, "files": []},
            "process_chapters": {"skip": False, "files": []},
            "build_index": {"skip": False, "files": []},
            "generate_summary": {"skip": False, "files": []},
        }

        # 定义所有文件路径
        from src.config.settings import DATA_ROOT
        doc_json_folder = os.path.join(self.agent.json_data_path, doc_name)
        json_path = os.path.join(doc_json_folder, "data.json")
        structure_json_path = os.path.join(doc_json_folder, "structure.json")
        chunk_json_path = os.path.join(doc_json_folder, "chunks.json")
        image_folder = os.path.join(self.agent.pdf_image_path, doc_name)
        vector_db_path = Path(DATA_ROOT) / "vector_db" / f"{doc_name}_data_index"
        summary_txt_path = os.path.join(DATA_ROOT, "output", f"{doc_name}_brief_summary.md")

        # 检查每个阶段的文件
        logger.info(f"🔍 [CheckCache] 开始检查各阶段文件...")

        # 1. 检查 parse 阶段
        if Path(json_path).exists():
            logger.info(f"✅ [CheckCache] parse: JSON文件存在")
            stage_status["parse"]["skip"] = True
            stage_status["parse"]["files"] = [image_folder, json_path] if Path(image_folder).exists() else [json_path]

            # 尝试加载 PDF 数据
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    pdf_data_list = json.load(f)
                state["pdf_data_list"] = pdf_data_list
                state["json_data_dict"] = {str(item.get("page", i+1)): item.get("data", "") for i, item in enumerate(pdf_data_list)}
                state["raw_data"] = "\n\n".join([f"[Page {item.get('page', i+1)}]\n{item.get('data', '')}" for i, item in enumerate(pdf_data_list)])
                logger.info(f"   📥 已加载 PDF 数据: {len(pdf_data_list)} 页")
            except Exception as e:
                logger.warning(f"⚠️  [CheckCache] PDF 数据加载失败: {e}")
                stage_status["parse"]["skip"] = False
        else:
            logger.info(f"❌ [CheckCache] parse: JSON文件不存在，需要执行")

        # 2. 检查 extract_structure 阶段
        if Path(structure_json_path).exists():
            logger.info(f"✅ [CheckCache] extract_structure: 结构文件存在")
            stage_status["extract_structure"]["skip"] = True
            stage_status["extract_structure"]["files"] = [structure_json_path]

            try:
                with open(structure_json_path, 'r', encoding='utf-8') as f:
                    structure_data = json.load(f)

                if isinstance(structure_data, dict):
                    if "agenda_dict" in structure_data:
                        state["agenda_dict"] = structure_data.get("agenda_dict", {})
                        state["has_toc"] = structure_data.get("has_toc", False)
                    else:
                        state["agenda_dict"] = structure_data
                        state["has_toc"] = True

                    logger.info(f"   📥 已加载结构: {len(state['agenda_dict'])} 个章节, has_toc={state.get('has_toc')}")
                else:
                    logger.warning(f"⚠️  [CheckCache] 结构数据格式错误（非字典类型）")
                    stage_status["extract_structure"]["skip"] = False
            except Exception as e:
                logger.warning(f"⚠️  [CheckCache] 结构数据加载失败: {e}")
                stage_status["extract_structure"]["skip"] = False
        else:
            logger.info(f"❌ [CheckCache] extract_structure: 结构文件不存在，需要执行")

        # 3. 检查 chunk_text 阶段
        if Path(chunk_json_path).exists():
            logger.info(f"✅ [CheckCache] chunk_text: 章节数据文件存在")
            stage_status["chunk_text"]["skip"] = True
            stage_status["chunk_text"]["files"] = [chunk_json_path]

            try:
                with open(chunk_json_path, 'r', encoding='utf-8') as f:
                    agenda_data_list = json.load(f)
                state["agenda_data_list"] = agenda_data_list
                logger.info(f"   📥 已加载章节数据: {len(agenda_data_list)} 个章节")
            except Exception as e:
                logger.warning(f"⚠️  [CheckCache] 章节数据加载失败: {e}")
                stage_status["chunk_text"]["skip"] = False
        else:
            logger.info(f"❌ [CheckCache] chunk_text: 章节数据文件不存在，需要执行")

        # 4 & 5. 检查 build_index 阶段（process_chapters 与 build_index 绑定）
        if vector_db_path.exists() and any(vector_db_path.iterdir()):
            logger.info(f"✅ [CheckCache] build_index: Vector DB存在")
            stage_status["build_index"]["skip"] = True
            stage_status["process_chapters"]["skip"] = True
            stage_status["build_index"]["files"] = [str(vector_db_path)]
            stage_status["process_chapters"]["files"] = [str(vector_db_path)]
            state["index_path"] = str(vector_db_path)

            # 从 Vector DB 加载 chapter_summaries 数据
            try:
                from src.core.vector_db.vector_db_client import VectorDBClient

                logger.info(f"   📥 正在从 Vector DB 加载章节摘要数据...")

                vector_db_client = VectorDBClient(str(vector_db_path), embedding_model=self.agent.embedding_model)

                chapter_summaries = {}
                chapter_refactors = {}
                raw_data_dict = {}

                if vector_db_client.vector_db and vector_db_client.vector_db.docstore:
                    for doc_id, doc in vector_db_client.vector_db.docstore._dict.items():
                        metadata = doc.metadata
                        doc_type = metadata.get("type")

                        if doc_type == "context":
                            title = metadata.get("title", "")
                            if title:
                                chapter_summaries[title] = doc.page_content
                                chapter_refactors[title] = metadata.get("refactor", "")
                                raw_data_dict[title] = metadata.get("raw_data", {})

                    state["chapter_summaries"] = chapter_summaries
                    state["chapter_refactors"] = chapter_refactors
                    state["raw_data_dict"] = raw_data_dict

                    logger.info(f"   📥 已从 Vector DB 加载: {len(chapter_summaries)} 个章节摘要")
                    logger.info(f"   ⏭️  process_chapters 和 build_index 都将跳过")
                else:
                    logger.warning(f"⚠️  [CheckCache] Vector DB 加载后为空")
                    stage_status["build_index"]["skip"] = False
                    stage_status["process_chapters"]["skip"] = False

            except Exception as e:
                logger.warning(f"⚠️  [CheckCache] 从 Vector DB 加载数据失败: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                stage_status["build_index"]["skip"] = False
                stage_status["process_chapters"]["skip"] = False
                logger.info(f"   ❌ 需要重新执行 process_chapters 和 build_index")
        else:
            logger.info(f"❌ [CheckCache] build_index: Vector DB不存在，需要执行")
            logger.info(f"❌ [CheckCache] process_chapters: 需要执行")

        # 6. 检查 generate_summary 阶段
        if Path(summary_txt_path).exists():
            logger.info(f"✅ [CheckCache] generate_summary: 摘要文件存在")
            stage_status["generate_summary"]["skip"] = True
            stage_status["generate_summary"]["files"] = [summary_txt_path]

            try:
                with open(summary_txt_path, 'r', encoding='utf-8') as f:
                    brief_summary = f.read()
                state["brief_summary"] = brief_summary
                logger.info(f"   📥 已加载摘要: {len(brief_summary)} 字符")
            except Exception as e:
                logger.warning(f"⚠️  [CheckCache] 摘要加载失败: {e}")
                stage_status["generate_summary"]["skip"] = False
        else:
            logger.info(f"❌ [CheckCache] generate_summary: 摘要文件不存在，需要执行")

        # 保存阶段状态到 state
        state["stage_status"] = stage_status

        # 统计信息
        skip_count = sum(1 for s in stage_status.values() if s["skip"])
        total_count = len(stage_status)
        logger.info(f"\n🔍 [CheckCache] 检查完成: {skip_count}/{total_count} 个阶段可跳过")

        # 详细输出每个阶段的状态
        for stage_name, status_info in stage_status.items():
            skip_status = "✅ 跳过" if status_info["skip"] else "❌ 执行"
            logger.debug(f"   {stage_name}: {skip_status}")

        # 更新 registry 状态（同步已有文件）
        for stage_name, status_info in stage_status.items():
            if status_info["skip"]:
                self.agent.doc_registry.update_stage_status(
                    doc_name=doc_name,
                    stage_name=stage_name,
                    status="completed",
                    output_files=status_info["files"]
                )

        return state

    async def parse_document(self, state: IndexingState) -> IndexingState:
        """
        步骤1：解析文档内容

        根据 check_cache 设置的标志决定是否跳过
        """
        logger.info(f"📄 [Parse] ========== 步骤1: 解析文档 ==========")
        logger.info(f"📄 [Parse] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        if stage_status.get("parse", {}).get("skip"):
            logger.info(f"⏭️  [Parse] 已有缓存数据，跳过解析")
            state["status"] = "parsed"
            return state

        logger.info(f"📄 [Parse] 开始解析文档...")

        doc_name = state["doc_name"]
        doc_type = state.get("doc_type")

        try:
            doc_path = state["doc_path"]

            # 初始化 generated_files（如果不存在）
            if "generated_files" not in state:
                state["generated_files"] = {
                    "images": [],
                    "json_data": "",
                    "vector_db": "",
                    "summaries": []
                }

            if doc_type == "pdf":
                logger.info(f"📄 [Parse] 使用PDF提取器处理: {doc_path}")

                pdf_file_name = doc_name
                logger.info(f"📄 [Parse] PDF文件名（无扩展名）: {pdf_file_name}")

                # 提取PDF数据（调用工具方法）
                logger.info(f"📄 [Parse] 开始调用 extract_pdf_data_impl...")
                extract_result = await self.agent.tools.extract_pdf_data_impl(pdf_file_name)
                logger.info(f"📄 [Parse] PDF数据提取完成")

                pdf_data_list = extract_result["pdf_data_list"]
                if not pdf_data_list:
                    raise ValueError(f"PDF提取失败，未获取任何数据: {doc_path}")

                # 将提取的数据转换为原始文本
                raw_data = "\n\n".join([
                    f"[Page {item.get('page', i+1)}]\n{item.get('data', '')}"
                    for i, item in enumerate(pdf_data_list)
                ])

                # 创建 json_data_dict（以页码为key）
                json_data_dict = {
                    str(item.get("page", i+1)): item.get("data", "")
                    for i, item in enumerate(pdf_data_list)
                }

                # 直接在 state 上修改
                state["raw_data"] = raw_data
                state["pdf_data_list"] = pdf_data_list
                state["json_data_dict"] = json_data_dict
                state["generated_files"]["images"] = extract_result["image_paths"]
                state["generated_files"]["json_data"] = extract_result["json_path"]
                state["status"] = "parsed"

                logger.info(f"✅ [Parse] PDF解析完成，提取 {len(pdf_data_list)} 页，总长度: {len(raw_data)} 字符")
                logger.info(f"📁 [Parse] 生成文件: 图片{len(state['generated_files']['images'])}个, JSON: {state['generated_files']['json_data']}")

                # 更新阶段状态
                image_folder = extract_result.get("image_folder", "")
                json_path = extract_result.get("json_path", "")
                output_files = []
                if image_folder:
                    output_files.append(image_folder)
                if json_path:
                    output_files.append(json_path)

                self.agent.doc_registry.update_stage_status(
                    doc_name=doc_name,
                    stage_name="parse",
                    status="completed",
                    output_files=output_files
                )

            elif doc_type == "url":
                logger.info(f"📄 [Parse] 使用Web内容提取器处理: {doc_path}")

                # doc_path 指向 SearchAgent.utils.save_web_content() 保存的 JSON
                # 结构：{"url", "url_hash", "timestamp", "content": {"text", "html", "json"}, "metadata"}
                with open(doc_path, 'r', encoding='utf-8') as f:
                    web_data = json.load(f)

                full_text = (web_data.get("content", {}) or {}).get("text", "") or ""
                if not full_text.strip():
                    raise ValueError(f"Web内容为空，无法解析: {doc_path}")

                # 将正文按固定长度切成"虚拟页"，与 PDF 提取产物完全同构，
                # 使下游 extract_structure/chunk_text/process_chapters/build_index
                # 无需任何改动即可复用（包括 analyze_full_structure_impl 的智能分段能力）
                virtual_page_chars = 2500
                pdf_data_list = [
                    {"page": i + 1, "data": full_text[i * virtual_page_chars:(i + 1) * virtual_page_chars]}
                    for i in range((len(full_text) + virtual_page_chars - 1) // virtual_page_chars)
                ]

                raw_data = "\n\n".join([
                    f"[Page {item['page']}]\n{item['data']}"
                    for item in pdf_data_list
                ])
                json_data_dict = {str(item["page"]): item["data"] for item in pdf_data_list}

                # 落盘 data.json，格式与 PDF 路径一致，使 check_cache 能对 url 文档同样生效
                doc_json_folder = os.path.join(self.agent.json_data_path, doc_name)
                os.makedirs(doc_json_folder, exist_ok=True)
                output_json_path = os.path.join(doc_json_folder, "data.json")
                with open(output_json_path, 'w', encoding='utf-8') as f:
                    json.dump(pdf_data_list, f, ensure_ascii=False, indent=2)

                state["raw_data"] = raw_data
                state["pdf_data_list"] = pdf_data_list
                state["json_data_dict"] = json_data_dict
                state["generated_files"]["json_data"] = output_json_path
                state["status"] = "parsed"

                logger.info(f"✅ [Parse] Web内容解析完成，切分为 {len(pdf_data_list)} 个虚拟页，总长度: {len(full_text)} 字符")

                self.agent.doc_registry.update_stage_status(
                    doc_name=doc_name,
                    stage_name="parse",
                    status="completed",
                    output_files=[output_json_path]
                )

            else:
                raise ValueError(f"不支持的文档类型: {doc_type}")

            return state

        except Exception as e:
            logger.error(f"❌ [Parse] 解析失败: {e}")
            state["status"] = "error"
            state["error"] = str(e)

            # 更新阶段状态为失败
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="parse",
                status="failed",
                output_files=[]
            )

            return state

    async def extract_structure(self, state: IndexingState) -> IndexingState:
        """
        步骤2：提取文档目录结构

        策略：
        1. 先尝试从前 5-10 页提取目录（快速）
        2. 如果没找到，分析全文结构（慢但全面）
        """
        logger.info(f"📚 [ExtractStructure] ========== 步骤2: 提取文档结构 ==========")
        logger.info(f"📚 [ExtractStructure] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        extract_status = stage_status.get("extract_structure", {})
        should_skip = extract_status.get("skip", False)
        if should_skip:
            logger.info(f"⏭️  [ExtractStructure] 已有缓存数据，跳过结构提取")
            logger.info(f"📚 [ExtractStructure] 已有 {len(state.get('agenda_dict', {}))} 个章节")
            return state

        logger.info(f"📚 [ExtractStructure] 开始提取文档结构...")

        doc_name = state["doc_name"]
        doc_type = state.get("doc_type")

        # 非 PDF/URL 类型没有结构可提取
        if doc_type not in ("pdf", "url"):
            logger.info(f"不支持结构提取的文档类型（{doc_type}），跳过")
            state["has_toc"] = False
            state["agenda_dict"] = {}
            return state

        # 定义结构文件路径（使用文档文件夹）
        doc_json_folder = os.path.join(self.agent.json_data_path, doc_name)
        structure_json_path = os.path.join(doc_json_folder, "structure.json")

        if doc_type == "url":
            # Web 内容没有 PDF 式目录页可快速提取，直接走全文智能分段
            # （analyze_full_structure_impl 本身按 split_pdf_raw_data 分块调用 LLM
            #  识别章节标题，天然能处理任意长度文本，也能识别文中已有的小标题结构；
            #  失败时兜底为"整篇当一个章节"）
            try:
                pdf_data_list = state.get("pdf_data_list", [])
                if not pdf_data_list:
                    logger.warning("虚拟页数据为空，无法提取结构")
                    state["has_toc"] = False
                    state["agenda_dict"] = {}
                    return state

                logger.info("🔍 [ExtractStructure] Web内容：直接分析全文结构")
                agenda_dict = await self.agent.tools.analyze_full_structure_impl(pdf_data_list)

                state["agenda_dict"] = agenda_dict
                state["has_toc"] = False
                logger.info(f"✅ [ExtractStructure] Web内容结构分析完成: {len(agenda_dict)} 个章节")

                structure_data = {"agenda_dict": agenda_dict, "has_toc": False}
                os.makedirs(os.path.dirname(structure_json_path), exist_ok=True)
                with open(structure_json_path, 'w', encoding='utf-8') as f:
                    json.dump(structure_data, f, ensure_ascii=False, indent=2)

                self.agent.doc_registry.update_stage_status(
                    doc_name=doc_name,
                    stage_name="extract_structure",
                    status="completed",
                    output_files=[structure_json_path]
                )
                return state

            except Exception as e:
                logger.error(f"❌ [ExtractStructure] Web内容结构提取失败: {e}")
                state["status"] = "error"
                state["error"] = str(e)
                self.agent.doc_registry.update_stage_status(
                    doc_name=doc_name,
                    stage_name="extract_structure",
                    status="failed",
                    output_files=[]
                )
                return state

        try:
            pdf_data_list = state.get("pdf_data_list", [])
            if not pdf_data_list:
                logger.warning("PDF数据为空，无法提取结构")
                state["has_toc"] = False
                state["agenda_dict"] = {}
                return state

            # 策略1：尝试从前几页快速提取目录
            logger.info("🚀 [ExtractStructure] 策略1: 尝试从前10页提取目录")
            agenda_dict, has_toc = await self.agent.tools.extract_toc_from_pages_impl(
                pdf_data_list,
                max_pages=10
            )

            if has_toc and agenda_dict:
                # 成功找到目录
                logger.info(f"✅ [ExtractStructure] 检测到目录结构: {len(agenda_dict)} 个章节")
                state["agenda_dict"] = agenda_dict
                state["has_toc"] = True
            else:
                # 策略2：没找到目录，分析全文结构
                logger.info("🔍 [ExtractStructure] 策略2: 分析全文结构")
                agenda_dict = await self.agent.tools.analyze_full_structure_impl(pdf_data_list)

                state["agenda_dict"] = agenda_dict
                state["has_toc"] = False
                logger.info(f"✅ [ExtractStructure] 全文分析完成: {len(agenda_dict)} 个章节")

            # 打印目录信息
            logger.info("📑 [ExtractStructure] 文档目录结构:")
            for title, pages in list(state["agenda_dict"].items())[:5]:
                logger.info(f"  - {title}: 第 {pages[0]}-{pages[-1]} 页")
            if len(state["agenda_dict"]) > 5:
                logger.info(f"  ... 还有 {len(state['agenda_dict']) - 5} 个章节")

            # 保存结构数据到文件
            structure_data = {
                "agenda_dict": state["agenda_dict"],
                "has_toc": state["has_toc"]
            }
            try:
                os.makedirs(os.path.dirname(structure_json_path), exist_ok=True)
                with open(structure_json_path, 'w', encoding='utf-8') as f:
                    json.dump(structure_data, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 [ExtractStructure] 结构数据已保存: {structure_json_path}")
            except Exception as e:
                logger.warning(f"⚠️  [ExtractStructure] 保存结构数据失败: {e}")

            # 更新阶段状态
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="extract_structure",
                status="completed",
                output_files=[structure_json_path]
            )

            return state

        except Exception as e:
            logger.error(f"❌ [ExtractStructure] 结构提取失败: {e}")
            # 失败时设置默认值
            state["has_toc"] = False
            state["agenda_dict"] = {}

            # 更新阶段状态为失败
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="extract_structure",
                status="failed",
                output_files=[]
            )

            return state

    async def chunk_text(self, state: IndexingState) -> IndexingState:
        """
        步骤3：构建章节数据列表

        直接基于 extract_structure 得到的 agenda_dict 构建 agenda_data_list
        """
        logger.info(f"📦 [Chunk] ========== 步骤3: 构建章节数据列表 ==========")
        logger.info(f"📦 [Chunk] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        if stage_status.get("chunk_text", {}).get("skip"):
            logger.info(f"⏭️  [Chunk] 已有缓存数据，跳过章节数据构建")
            logger.info(f"📦 [Chunk] 已有 {len(state.get('agenda_data_list', []))} 个章节")
            return state

        logger.info(f"📦 [Chunk] 开始构建章节数据...")

        doc_name = state["doc_name"]

        # 定义章节数据文件路径（使用文档文件夹）
        doc_json_folder = os.path.join(self.agent.json_data_path, doc_name)
        chunk_json_path = os.path.join(doc_json_folder, "chunks.json")

        try:
            agenda_dict = state.get("agenda_dict", {})
            json_data_dict = state.get("json_data_dict", {})

            if not agenda_dict:
                logger.warning("agenda_dict 为空，无法构建章节数据")
                state["agenda_data_list"] = []
                state["status"] = "chunked"
                return state

            if not json_data_dict:
                logger.warning("json_data_dict 为空，无法构建章节数据")
                state["agenda_data_list"] = []
                state["status"] = "chunked"
                return state

            # 直接基于 agenda_dict 构建 agenda_data_list
            agenda_data_list = []

            for title, page_numbers in agenda_dict.items():
                # 收集该章节的所有页面数据
                chapter_data = {}

                for page_num in page_numbers:
                    page_key = str(page_num)
                    if page_key in json_data_dict:
                        chapter_data[page_key] = json_data_dict[page_key]
                    else:
                        logger.warning(f"页码 {page_key} 不在 json_data_dict 中")

                if chapter_data:
                    agenda_data_list.append({
                        "title": title,
                        "data": chapter_data,
                        "pages": page_numbers
                    })
                else:
                    logger.warning(f"章节 '{title}' 没有找到对应的数据")

            logger.info(f"✅ [Chunk] 章节数据构建完成: {len(agenda_data_list)} 个章节")

            # 打印章节信息
            for item in agenda_data_list:
                title = item.get("title", "未知")
                pages = item.get("pages", [])
                data_pages = len(item.get("data", {}))
                logger.info(f"  - {title}: {len(pages)} 页 (实际数据: {data_pages} 页)")

            # 保存章节数据到文件
            try:
                os.makedirs(os.path.dirname(chunk_json_path), exist_ok=True)
                with open(chunk_json_path, 'w', encoding='utf-8') as f:
                    json.dump(agenda_data_list, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 [Chunk] 章节数据已保存: {chunk_json_path}")
            except Exception as e:
                logger.warning(f"⚠️  [Chunk] 保存章节数据失败: {e}")

            # 直接在 state 上修改
            state["agenda_data_list"] = agenda_data_list
            state["status"] = "chunked"

            # 更新阶段状态
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="chunk_text",
                status="completed",
                output_files=[chunk_json_path]
            )

            return state

        except Exception as e:
            logger.error(f"❌ [Chunk] 章节数据构建失败: {e}")
            state["status"] = "error"
            state["error"] = str(e)

            # 更新阶段状态为失败
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="chunk_text",
                status="failed",
                output_files=[]
            )

            return state

    async def process_chapters(self, state: IndexingState) -> IndexingState:
        """
        步骤4：处理章节（并行生成摘要和重构内容）

        对每个章节：
        1. 生成摘要（summary）
        2. 重构内容（refactor）
        """
        logger.info(f"📝 [ProcessChapters] ========== 步骤4: 处理章节 ==========")
        logger.info(f"📝 [ProcessChapters] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        if stage_status.get("process_chapters", {}).get("skip"):
            logger.info(f"⏭️  [ProcessChapters] 已有缓存数据，跳过章节处理")
            logger.info(f"📝 [ProcessChapters] 已有 {len(state.get('chapter_summaries', {}))} 个章节摘要")
            return state

        logger.info(f"📝 [ProcessChapters] 开始处理章节...")

        doc_name = state["doc_name"]

        try:
            from src.core.parallel import ChapterProcessor
            from .prompts import IndexingRole
            from src.agents.common.prompts import CommonRole

            agenda_data_list = state.get("agenda_data_list", [])
            logger.info(f"📝 [ProcessChapters] 章节数量: {len(agenda_data_list)}")

            if not agenda_data_list:
                logger.warning("📝 [ProcessChapters] ⚠️ agenda_data_list 为空，跳过章节处理")
                state["chapter_summaries"] = {}
                state["chapter_refactors"] = {}
                state["raw_data_dict"] = {}
                state["status"] = "summarized"
                return state

            # 使用并行处理工具
            logger.info(f"开始并行处理 {len(agenda_data_list)} 个章节...")

            # 直接使用异步方法（因为当前已经在async上下文中）
            processor = ChapterProcessor(self.agent.llm, max_concurrent=10)
            chapter_results = await processor.process_chapters_summary_and_refactor(
                agenda_data_list=agenda_data_list,
                summary_role=IndexingRole.CONTENT_SUMMARY,
                refactor_role=CommonRole.CONTENT_MERGE
            )

            # 处理结果
            chapter_summaries = {}
            chapter_refactors = {}
            raw_data_dict = {}

            for title, summary, refactor_content, _, data in chapter_results:
                chapter_summaries[title] = summary
                chapter_refactors[title] = refactor_content
                raw_data_dict[title] = data

                logger.info(f"✅ 章节处理完成: {title}")

            logger.info(f"✅ [ProcessChapters] 所有章节处理完成: {len(chapter_summaries)} 个章节")
            logger.info(f"📌 [ProcessChapters] 数据将在 build_index 阶段存入 Vector DB")

            # 直接在 state 上修改
            state["chapter_summaries"] = chapter_summaries
            state["chapter_refactors"] = chapter_refactors
            state["raw_data_dict"] = raw_data_dict
            state["status"] = "summarized"

            # 更新阶段状态（数据存储在 vector db 中，无单独文件）
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="process_chapters",
                status="completed",
                output_files=[]  # 数据在 vector db 中
            )

            return state

        except Exception as e:
            logger.error(f"❌ [ProcessChapters] 章节处理失败: {e}")
            state["status"] = "error"
            state["error"] = str(e)

            # 更新阶段状态为失败
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="process_chapters",
                status="failed",
                output_files=[]
            )

            return state

    async def build_index(self, state: IndexingState) -> IndexingState:
        """
        步骤5：构建向量索引

        基于章节摘要构建 Document 对象：
        1. type="context": 章节摘要作为检索内容
        2. type="title": 章节标题作为检索内容
        3. type="structure": 文档结构信息
        """
        logger.info(f"🔨 [BuildIndex] ========== 步骤5: 构建向量索引 ==========")
        logger.info(f"🔨 [BuildIndex] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        if stage_status.get("build_index", {}).get("skip"):
            logger.info(f"⏭️  [BuildIndex] 已有 Vector DB，跳过构建")
            logger.info(f"🔨 [BuildIndex] Vector DB 路径: {state.get('index_path')}")
            state["status"] = "indexed"
            return state

        logger.info(f"🔨 [BuildIndex] 开始构建向量索引...")

        doc_name = state["doc_name"]

        # 构建索引路径
        from src.config.settings import DATA_ROOT
        index_path = str(Path(DATA_ROOT) / "vector_db" / f"{doc_name}_data_index")

        try:
            from langchain.docstore.document import Document
            from src.core.vector_db.vector_db_client import VectorDBClient

            chapter_summaries = state.get("chapter_summaries", {})
            chapter_refactors = state.get("chapter_refactors", {})
            raw_data_dict = state.get("raw_data_dict", {})
            agenda_dict = state.get("agenda_dict", {})

            if not chapter_summaries:
                logger.warning("章节摘要为空，无法构建索引")
                state["status"] = "error"
                state["error"] = "章节摘要为空"
                return state

            # 构建 Document 列表
            vector_db_docs = []

            logger.info("开始构建 Document 对象...")

            # 遍历每个章节
            for title, summary in chapter_summaries.items():
                refactor_content = chapter_refactors.get(title, "")
                raw_data = raw_data_dict.get(title, {})
                pages = agenda_dict.get(title, [])

                # Document 1: type="context" - 摘要作为检索内容
                vector_db_docs.append(
                    Document(
                        page_content=summary,
                        metadata={
                            "type": "context",
                            "title": title,
                            "pages": pages,
                            "raw_data": raw_data,
                            "refactor": refactor_content,
                        }
                    )
                )

                # Document 2: type="title" - 标题作为检索内容
                vector_db_docs.append(
                    Document(
                        page_content=title,
                        metadata={
                            "type": "title",
                            "pages": pages,
                            "summary": summary,
                            "raw_data": raw_data,
                            "refactor": refactor_content,
                        }
                    )
                )

            # Document 3: type="structure" - 文档结构信息
            structure_doc = Document(
                page_content="Document Structure",
                metadata={
                    "type": "structure",
                    "agenda_dict": agenda_dict,
                    "doc_name": doc_name,
                    "total_chapters": len(agenda_dict)
                }
            )
            vector_db_docs.append(structure_doc)

            logger.info(f"Document 对象构建完成: {len(vector_db_docs)} 个文档")

            # 构建索引路径
            index_dir = Path(DATA_ROOT) / "vector_db" / f"{doc_name}_data_index"
            index_dir.mkdir(parents=True, exist_ok=True)
            index_path = str(index_dir)

            # 创建 VectorDBClient 并构建向量数据库
            vector_db_client = VectorDBClient(index_path, embedding_model=self.agent.embedding_model)
            vector_db_client.build_vector_db(vector_db_docs)

            logger.info(f"✅ [BuildIndex] 向量数据库构建完成: {index_path}")

            # 直接在 state 上修改
            state["index_path"] = index_path
            state["vector_db_docs"] = vector_db_docs
            if "generated_files" not in state:
                state["generated_files"] = {
                    "images": [],
                    "json_data": "",
                    "vector_db": "",
                    "summaries": []
                }
            state["generated_files"]["vector_db"] = index_path
            state["status"] = "indexed"

            # 更新阶段状态
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="build_index",
                status="completed",
                output_files=[index_path]
            )

            return state

        except Exception as e:
            logger.error(f"❌ [BuildIndex] 索引构建失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            state["status"] = "error"
            state["error"] = str(e)

            # 更新阶段状态为失败
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="build_index",
                status="failed",
                output_files=[]
            )
            return state

    async def generate_brief_summary(self, state: IndexingState) -> IndexingState:
        """
        步骤6：生成简要摘要（基于所有章节摘要）

        这是最后一步摘要生成，整合所有章节的摘要
        """
        logger.info(f"📝 [BriefSummary] ========== 步骤6: 生成简要摘要 ==========")
        logger.info(f"📝 [BriefSummary] 文档名称: {state['doc_name']}")

        # 检查是否应该跳过
        stage_status = state.get("stage_status", {})
        if stage_status.get("generate_summary", {}).get("skip"):
            logger.info(f"⏭️  [BriefSummary] 已有摘要文件，跳过生成")
            logger.info(f"📝 [BriefSummary] 摘要长度: {len(state.get('brief_summary', ''))} 字符")
            return state

        logger.info(f"📝 [BriefSummary] 开始生成简要摘要...")

        doc_name = state["doc_name"]

        # 定义摘要文件路径
        from src.config.settings import DATA_ROOT
        summary_txt_path = os.path.join(DATA_ROOT, "output", f"{doc_name}_brief_summary.md")

        try:
            chapter_summaries = state.get("chapter_summaries", {})
            logger.info(f"📝 [BriefSummary] 章节摘要数量: {len(chapter_summaries)}")

            if not chapter_summaries:
                logger.warning("章节摘要为空，无法生成简要摘要")
                state["brief_summary"] = ""
                return state

            # 复用 generate_summary_impl，传入章节摘要
            answer = await self.agent.tools.generate_summary_impl(
                context_data=chapter_summaries,
                doc_name=doc_name,
                session_id="brief_summary"
            )

            logger.info(f"✅ [BriefSummary] 简要摘要生成完成，长度: {len(answer)} 字符")

            # 保存摘要到文件
            try:
                os.makedirs(os.path.dirname(summary_txt_path), exist_ok=True)
                with open(summary_txt_path, 'w', encoding='utf-8') as f:
                    f.write(answer)
                logger.info(f"💾 [BriefSummary] 简要摘要已保存: {summary_txt_path}")

                # 更新 generated_files
                if "generated_files" not in state:
                    state["generated_files"] = {"images": [], "json_data": "", "vector_db": "", "summaries": []}
                if "summaries" not in state["generated_files"]:
                    state["generated_files"]["summaries"] = []
                state["generated_files"]["summaries"].append(summary_txt_path)

            except Exception as e:
                logger.warning(f"⚠️  [BriefSummary] 保存简要摘要失败: {e}")

            # 直接在 state 上修改
            state["brief_summary"] = answer

            # 更新阶段状态
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="generate_summary",
                status="completed",
                output_files=[summary_txt_path]
            )

            return state

        except Exception as e:
            logger.error(f"❌ [BriefSummary] 简要摘要生成失败: {e}")
            state["brief_summary"] = f"文档 {state['doc_name']} 的简要摘要（生成错误: {str(e)}）"

            # 更新阶段状态为失败
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="generate_summary",
                status="failed",
                output_files=[]
            )

            return state

    async def register_document(self, state: IndexingState) -> IndexingState:
        """
        步骤7：注册到文档库
        """
        logger.info(f"📋 [Register] ========== 步骤7: 注册文档 ==========")
        logger.info(f"📋 [Register] 文档名称: {state['doc_name']}")

        doc_name = state["doc_name"]

        try:
            # 获取生成的文件信息
            generated_files = state.get("generated_files", {
                "images": [],
                "json_data": "",
                "vector_db": "",
                "summaries": []
            })

            # 注册文档
            doc_id = self.agent.doc_registry.register(
                doc_name=state["doc_name"],
                doc_path=state["doc_path"],
                doc_type=state["doc_type"],
                index_path=state.get("index_path", ""),
                brief_summary=state.get("brief_summary", ""),
                metadata={},
                generated_files=generated_files
            )

            logger.info(f"✅ [Register] 文档注册完成: {doc_id}")
            logger.info(f"📁 [Register] 关联文件统计:")
            logger.info(f"  - 图片: {len(generated_files.get('images', []))} 个")
            logger.info(f"  - JSON: {1 if generated_files.get('json_data') else 0} 个")
            logger.info(f"  - 向量DB: {1 if generated_files.get('vector_db') else 0} 个")
            logger.info(f"  - 摘要: {len(generated_files.get('summaries', []))} 个")

            # ========== 提取并存储元数据（用于多PDF检索） ==========
            logger.info(f"")
            logger.info(f"📋 [Register] ========== 提取文档元数据 ==========")
            try:
                from .components import MetadataExtractor

                # 提取元数据
                extractor = MetadataExtractor(self.agent.llm)
                metadata_enhanced = await extractor.extract_metadata(
                    doc_name=doc_name,
                    brief_summary=state.get("brief_summary", ""),
                    structure=state.get("agenda_dict", {})
                )

                # 保存元数据到doc_registry（使用并发安全的方法）
                success = self.agent.doc_registry.update_metadata(
                    doc_id=doc_id,
                    metadata_key="metadata_enhanced",
                    metadata_value=metadata_enhanced
                )
                if success:
                    logger.info(f"✅ [Register] 元数据已保存到文档注册表")
                else:
                    logger.warning(f"⚠️ [Register] 元数据保存失败，文档ID不存在: {doc_id}")

                # 添加到元数据向量数据库
                from src.core.vector_db.metadata_db import MetadataVectorDB

                metadata_db = MetadataVectorDB()
                metadata_db.add_document(
                    doc_id=doc_id,
                    doc_name=doc_name,
                    embedding_summary=metadata_enhanced.get("embedding_summary", "")
                )

                logger.info(f"✅ [Register] 元数据已添加到向量数据库")

            except Exception as e:
                logger.error(f"❌ [Register] 元数据提取/存储失败: {e}")
                logger.warning(f"⚠️  [Register] 跳过元数据处理，继续完成注册")

            logger.info(f"")

            # 直接在 state 上修改
            state["doc_id"] = doc_id
            state["status"] = "completed"
            state["is_complete"] = True  # ✅ 设置完成标志

            # 更新阶段状态 (注册阶段完成就意味着整个流程完成)
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="register",
                status="completed",
                output_files=[]  # 注册本身不生成文件
            )

            return state

        except Exception as e:
            logger.error(f"❌ [Register] 文档注册失败: {e}")
            state["status"] = "error"
            state["error"] = str(e)

            # 更新阶段状态为失败
            self.agent.doc_registry.update_stage_status(
                doc_name=doc_name,
                stage_name="register",
                status="failed",
                output_files=[]
            )

            return state
