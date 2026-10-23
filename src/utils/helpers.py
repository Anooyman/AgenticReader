import fitz  # 导入pymupdf库，它在导入时别名为fitz
import json
import os
import unicodedata
import re
import logging
from typing import List, Optional, Dict, Any

# 导入新的工具库
from .file_operations import SafeFileOperations
from .error_handler import retry_on_error, error_context
from .exceptions import FileProcessingError

logger = logging.getLogger(__name__)

def read_images_in_directory(directory_path: str) -> List[str]:
    """
    读取指定目录下所有支持格式的图片文件路径。
    Read all supported image files in a directory.
    Args:
        directory_path (str): 目录路径。
    Returns:
        List[str]: 图片文件路径列表。
    """
    # 导入常量配置
    from src.config.constants import PDFConstants

    image_files = []
    valid_image_extensions = PDFConstants.SUPPORTED_IMAGE_EXTENSIONS
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            file_extension = os.path.splitext(file)[1].lower()
            if file_extension in valid_image_extensions:
                image_path = os.path.join(root, file)
                image_files.append(image_path)
    logger.info(f"读取到{len(image_files)}张图片 in {directory_path}")
    return image_files

def makedir(path: str) -> None:
    """
    创建目录（如果不存在）

    Args:
        path (str): 要创建的目录路径

    Returns:
        None
    """
    try:
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            logger.info(f"目录已创建: {path}")
        else:
            logger.debug(f"目录已存在: {path}")
    except OSError as e:
        logger.error(f"创建目录失败 {path}: {e}")
        raise

@retry_on_error(max_retries=2, exceptions=(Exception,))
def pdf_to_images(pdf_path: str, output_folder: str, dpi: int = 300, quality: str = "high") -> Dict[str, Any]:
    """
    将 PDF 文件每一页转换为高质量图片并保存到指定文件夹。

    增强功能：
    - 添加错误重试机制
    - 改进内存管理
    - 返回转换统计信息
    - 添加进度跟踪

    Args:
        pdf_path (str): PDF 文件路径
        output_folder (str): 图片保存文件夹
        dpi (int): 图片分辨率，默认300 DPI。建议值：150(快速), 300(高质量), 600(超高质量)
        quality (str): 图片质量级别 - "low"(2x), "medium"(3x), "high"(4x), "ultra"(5x)

    Returns:
        Dict[str, Any]: 转换结果统计信息

    Raises:
        FileProcessingError: PDF处理失败
    """
    import time
    start_time = time.time()

    try:
        # 验证输入文件
        if not os.path.exists(pdf_path):
            raise FileProcessingError(f"PDF文件不存在: {pdf_path}", "FILE_NOT_FOUND")

        # 确保输出目录存在
        logger.debug(f"准备创建输出目录: {output_folder}")
        try:
            # 使用 is_directory=True 参数明确指定这是目录路径
            SafeFileOperations.ensure_directory(output_folder)
            logger.info(f"输出目录已准备: {output_folder}")
        except Exception as e:
            logger.error(f"创建输出目录失败: {output_folder}, 错误: {e}")
            # 尝试直接使用os.makedirs作为备用方案
            try:
                os.makedirs(output_folder, exist_ok=True)
                logger.info(f"使用备用方法创建目录成功: {output_folder}")
            except Exception as backup_e:
                raise FileProcessingError(f"无法创建输出目录: {backup_e}", "DIRECTORY_CREATION_ERROR")

        # 导入常量配置
        from src.config.constants import PDFConstants

        # 计算缩放因子
        dpi_scale = dpi / 72.0
        quality_scale_factor = PDFConstants.QUALITY_LEVELS.get(quality, {}).get("scale", 4.0)
        final_scale = max(dpi_scale, quality_scale_factor)

        logger.info(f"开始PDF转图片: {pdf_path}")
        logger.info(f"参数: DPI={dpi}, 质量={quality}, 缩放={final_scale:.1f}x")

        # 转换统计
        conversion_stats = {
            "total_pages": 0,
            "successful_pages": 0,
            "failed_pages": 0,
            "total_size_mb": 0,
            "processing_time": 0,
            "output_files": []
        }

        doc = None
        try:
            doc = fitz.open(pdf_path)
            conversion_stats["total_pages"] = doc.page_count

            for page_num in range(doc.page_count):
                try:
                    page = doc[page_num]

                    # 创建变换矩阵
                    matrix = fitz.Matrix(final_scale, final_scale)

                    # 获取pixmap并立即处理
                    pix = page.get_pixmap(
                        matrix=matrix,
                        alpha=False,
                        annots=True,
                        clip=None
                    )

                    # 构建输出路径
                    image_path = os.path.join(output_folder, f"page_{page_num + 1}.png")

                    # 保存图片
                    pix.save(image_path)

                    # 记录文件信息
                    file_size = os.path.getsize(image_path)
                    conversion_stats["total_size_mb"] += file_size / (1024 * 1024)
                    conversion_stats["output_files"].append({
                        "page": page_num + 1,
                        "path": image_path,
                        "size_mb": file_size / (1024 * 1024),
                        "dimensions": f"{pix.width}x{pix.height}"
                    })

                    conversion_stats["successful_pages"] += 1

                    # 立即释放内存
                    pix = None
                    page = None

                    # 每10页记录一次进度
                    if (page_num + 1) % 10 == 0:
                        logger.info(f"已处理 {page_num + 1}/{doc.page_count} 页")

                except Exception as e:
                    conversion_stats["failed_pages"] += 1
                    logger.error(f"第{page_num + 1}页转换失败: {e}")
                    continue

        finally:
            # 确保文档被关闭
            if doc:
                doc.close()
                doc = None

        # 计算处理时间
        conversion_stats["processing_time"] = time.time() - start_time

        logger.info(f"PDF转换完成: 成功{conversion_stats['successful_pages']}页, "
                   f"失败{conversion_stats['failed_pages']}页, "
                   f"总大小{conversion_stats['total_size_mb']:.2f}MB, "
                   f"耗时{conversion_stats['processing_time']:.2f}秒")

        return conversion_stats

    except Exception as e:
        raise FileProcessingError(f"PDF转图片失败: {e}", "PDF_CONVERSION_ERROR")

def extract_page_num(path: str) -> Optional[str]:
    """
    从图片路径中提取页码数字。
    Extract page number from image file path.
    Args:
        path (str): 图片文件路径。
    Returns:
        Optional[str]: 提取到的页码数字，未找到则为 None。
    """
    file_name = os.path.basename(path)
    pattern = r'\d+'
    match = re.search(pattern, file_name)

    if match:
        number = match.group(0)
        logger.debug(f"Extracted page number {number} from {file_name}")
        return number
    else:
        logger.warning(f"未找到数字 in {file_name}。")
        return None

def extract_data_from_LLM_res(content: str) -> Optional[Dict[str, Any]]:
    """
    从LLM响应中提取JSON数据，安全地解析各种格式

    Args:
        content: LLM响应内容，可能包含JSON格式或markdown代码块中的JSON

    Returns:
        dict: 解析后的数据，失败时返回None
    """
    data = None

    # 如果输入为空或None，直接返回None
    if not content:
        logger.warning("extract_data_from_LLM_res: 输入内容为空")
        return None

    try:
        # 首先尝试直接解析JSON
        data = json.loads(content)
        logger.debug("成功直接解析JSON内容")
        return data
    except json.JSONDecodeError as e:
        logger.debug(f"直接JSON解析失败: {e}，尝试从markdown代码块中提取")

        # 尝试从markdown代码块中提取JSON
        # 支持多种可能的代码块格式
        patterns = [
            r'```json\n(.*?)```',      # 标准json代码块
            r'```\n(.*?)```',          # 普通代码块
            r'`([^`]*)`',              # 单行代码块
        ]

        for pattern in patterns:
            try:
                match = re.search(pattern, content, re.DOTALL)
                if match:
                    json_str = match.group(1).strip()
                    logger.debug(f"从代码块中提取到内容: {json_str[:100]}...")

                    # 安全地尝试解析提取的JSON字符串
                    data = json.loads(json_str)
                    logger.debug("成功从代码块中解析JSON")
                    return data

            except json.JSONDecodeError as parse_error:
                logger.warning(f"代码块JSON解析失败 (pattern: {pattern}): {parse_error}")
                continue
            except Exception as unexpected_error:
                logger.error(f"提取JSON时发生意外错误: {unexpected_error}")
                continue

        # 如果所有方法都失败了，记录警告并返回None
        logger.warning("无法从内容中提取有效的JSON数据")
        logger.debug(f"原始内容: {content[:200]}...")

    except Exception as e:
        logger.error(f"extract_data_from_LLM_res发生意外错误: {e}")

    return None

def full_to_half(text: str) -> str:
    """
    将全角字符转换为半角

    Args:
        text (str): 输入的文本字符串

    Returns:
        str: 转换后的半角字符串
    """
    normalized = []
    for char in text:
        # 全角转半角
        if unicodedata.east_asian_width(char) == 'F':
            normalized_char = unicodedata.normalize('NFKC', char)
            normalized.append(normalized_char)
        else:
            normalized.append(char)
    return ''.join(normalized)

def normalize_chapter(name: str) -> str:
    """
    标准化章节名称

    Args:
        name (str): 原始章节名称

    Returns:
        str: 标准化后的章节名称
    """
    # 1. 全角转半角
    name = full_to_half(name)
    # 2. 移除所有标点和空白
    name = re.sub(r'[^\w\u4e00-\u9fa5]', '', name)
    # 3. 转为小写（如果有英文）
    return name.lower()

def deduplicate_by_title(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    根据标题去重数据项

    Args:
        data (List[Dict[str, Any]]): 包含标题的数据项列表

    Returns:
        List[Dict[str, Any]]: 去重后的数据项列表
    """
    seen = set()
    result = []
    for item in data:
        title = normalize_chapter(item.get('title', ''))
        if title not in seen:
            seen.add(title)
            result.append(item)
    return result

def group_data_by_sections_with_titles(total_sections: List[Dict[str, Any]], raw_data: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    根据章节信息对数据进行分组

    增强功能：
    - 改进错误处理
    - 添加数据验证
    - 优化内存使用
    - 增强日志记录

    Args:
        total_sections: 章节信息列表
        raw_data: 原始数据列表

    Returns:
        tuple: (数据结果, 议程结果)

    Raises:
        ValidationError: 数据验证失败
    """
    logger.info(f"开始分组数据，输入章节数: {len(total_sections)}, 原始数据条数: {len(raw_data)}")

    # 输入验证
    if not total_sections:
        logger.warning("章节列表为空，返回空结果")
        return [], []

    if not raw_data:
        logger.warning("原始数据为空，返回空结果")
        return [], []

    try:
        with error_context("数据分组处理", reraise=True) as error_handler:
            # 去重章节
            unsort_sections = deduplicate_by_title(total_sections)
            logger.info(f"去重后章节数: {len(unsort_sections)}")

            if not unsort_sections:
                logger.warning("去重后章节列表为空")
                return [], []

            # 安全排序章节
            sections = _safe_sort_sections(unsort_sections)
            logger.debug(f"章节排序完成，共 {len(sections)} 个章节")

            # 构建页码到内容的映射
            page_to_data = _build_page_mapping(raw_data)
            logger.debug(f"构建页码映射完成，共 {len(page_to_data)} 页")

            # 找到最大页码
            max_page = max((int(item['page']) for item in raw_data), default=0)
            logger.debug(f"最大页码: {max_page}")

            # 按相同页码分组
            groups = _group_sections_by_page(sections)
            logger.debug(f"章节分组完成，共 {len(groups)} 组")

            # 处理每个组并生成结果
            data_result, agenda_result = _process_section_groups(
                groups, page_to_data, max_page
            )

            logger.info(f"数据分组完成: 数据结果 {len(data_result)} 项, 议程结果 {len(agenda_result)} 项")
            return data_result, agenda_result

    except Exception as e:
        from .exceptions import ValidationError
        raise ValidationError(f"数据分组失败: {e}")


def _safe_sort_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """安全地对章节进行排序"""
    try:
        return sorted(
            sections,
            key=lambda x: int(x.get("page", float('inf'))) if x.get("page") else float('inf')
        )
    except (ValueError, TypeError) as e:
        logger.warning(f"章节排序失败，使用原始顺序: {e}")
        return sections


def _build_page_mapping(raw_data: List[Dict[str, Any]]) -> Dict[int, Any]:
    """构建页码到内容的映射"""
    page_to_data = {}

    for item in raw_data:
        try:
            page = int(item['page'])
            page_to_data[page] = item.get('data', "")
        except (ValueError, KeyError) as e:
            logger.warning(f"跳过无效数据项: {e}")
            continue

    return page_to_data


def _group_sections_by_page(sections: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """按相同页码对章节进行分组"""
    if not sections:
        return []

    groups = []
    current_group = [sections[0]]
    current_page = int(sections[0].get('page', 0))

    for sec in sections[1:]:
        try:
            page = int(sec.get('page', 0))
            if page == current_page:
                current_group.append(sec)
            else:
                groups.append(current_group)
                current_group = [sec]
                current_page = page
        except (ValueError, TypeError):
            logger.warning(f"跳过页码无效的章节: {sec}")
            continue

    if current_group:
        groups.append(current_group)

    return groups


def _process_section_groups(groups: List[List[Dict[str, Any]]],
                          page_to_data: Dict[int, Any],
                          max_page: int) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """处理章节组并生成最终结果"""
    data_result = []
    agenda_result = []

    for group_idx, group in enumerate(groups):
        # 获取下一组的起始页码
        if group_idx < len(groups) - 1:
            next_group_start = int(groups[group_idx + 1][0].get('page', max_page))
        else:
            next_group_start = max_page

        # 处理组内每个章节
        for sec_idx, sec in enumerate(group):
            try:
                start = int(sec.get('page', 0))

                # 确定结束页码
                if sec_idx == len(group) - 1:  # 组内最后一个章节
                    end = next_group_start if group_idx < len(groups) - 1 else max_page
                else:
                    end = start  # 组内非最后章节只包含当前页

                # 生成页码范围
                pages = [start] if start == end else list(range(start, end + 1))

                # 收集章节数据
                section_data = {}
                for page in pages:
                    section_data[page] = page_to_data.get(page, "")

                # 添加到结果
                data_result.append({
                    'title': sec.get('title', f'未命名章节_{len(data_result)}'),
                    'pages': pages,
                    'data': section_data
                })

                agenda_result.append({
                    'title': sec.get('title', f'未命名章节_{len(agenda_result)}'),
                    'pages': pages,
                })

            except (ValueError, TypeError) as e:
                logger.error(f"处理章节时出错: {e}, 章节: {sec}")
                continue

    return data_result, agenda_result
