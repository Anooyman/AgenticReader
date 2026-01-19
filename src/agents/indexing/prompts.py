"""
IndexingAgent Prompts Configuration

定义 IndexingAgent 使用的所有 system prompts。
用于文档解析、内容提取、总结和索引构建。
"""

# Indexing role constants
class IndexingRole:
    """IndexingAgent 角色常量"""
    IMAGE_EXTRACT = "image_extract"  # 图片内容提取
    METADATA_EXTRACT = "metadata_extract"  # 提取文档元数据
    CHAPTER_EXTRACT = "chapter_extract"  # 提取章节目录结构
    SUB_CHAPTER_EXTRACT = "sub_chapter_extract"  # 提取子章节目录
    CONTENT_SUMMARY = "content_summary"  # 内容总结


INDEXING_PROMPTS = {
    IndexingRole.IMAGE_EXTRACT: """Analyze the content of an image, extract relevant information, and organize it according to human reading habits into markdown format based on the data type (e.g., text, table, image, code, formulas, flowcharts).

# Key Instructions

- **Text Content**: Extract natural language content directly and organize it for human readability. Do not summarize or outline.
- **Table Data**:
  1. Generate a summary description based on the table title and content.
  2. Extract table information and describe it clearly in natural language.
- **Image Information**:
  1. Parse image content and understand the details.
  2. Generate a descriptive explanation based on the image title and its elements.
- **Code Blocks**: Extract and present code exactly as it appears in the image, preserving its original meaning in proper code formatting.
- **Formulas**: Convert relevant mathematical expressions or data into **LaTeX** format.
- **Flowcharts**:
  1. Analyze and interpret the content of the flowchart.
  2. Provide a clear, human-readable explanation based on the flowchart structure.
- **General Content**: Filter out meaningless information and retain only relevant and concise details. Return the details in markdown format in a way that aligns with human readability.

# Output Format

The extracted content should be formatted as follows:

## Text Content
[Organized natural language text extracted from the image.]

## Table Summary
[A brief summary interpreting the purpose and key points of the table.]

## Table Data
[Key table information rewritten into human-readable language.]

## Image Description
[A descriptive text of the content depicted in the image, organized for easy understanding.]

## Code
```
[Original code extracted from the image, formatted in code blocks.]
```

## Formulas
[Mathematical expressions converted to LaTeX format, with explanations if needed.]

## Flowchart Description
[A detailed, human-readable interpretation of the flowchart.]

# Steps

- **1. Extract Information**: Extract all forms of content from the image (text, tables, images, code, formulas, flowcharts, etc.).
- **2. Organize by Type**: Classify and process data according to type:
  - Text: Provide as-is but structured naturally.
  - Tables: Summarize first, then describe contents.
  - Images and Flowcharts: Offer detailed interpretations of visual content.
  - Code: Preserve and render in proper code blocks.
  - Formulas: Convert to LaTeX as needed.
- **3. Format in Markdown**: Ensure the final output is organized by type and presented in clear markdown syntax.
- **4. Exclude Irrelevant Data**: Discard meaningless or visually insignificant content.

# Notes

- All outputs should align with human reading habits and intentional sequences.
- For complex tables, images, or flowcharts, aim for clarity and simplicity when interpreting the data.
- Use only markdown syntax for formatting (e.g., bold/italic for emphasis, headers for sections, lists for organization). Do not mix content with unrelated context.
- Do not return a heading for a section whose content does not exist in the current image.

# Example

### Input:
[An image containing a table, an illustration, and a formula.]

### Output in Markdown:

## Text Content
"The image contains information about sales data and its impact across different regions over the last quarter."

## Table Summary
"The table provides an overview of sales figures categorized by region and type of product."

## Table Data
- **Region**: North America, Europe, Asia
- **Products**: Electronics, Furniture, Clothing
- **Sales Figures**:
  - North America: $1M Electronics, $500K Furniture, $600K Clothing
  - Europe: $800K Electronics, $300K Furniture, $400K Clothing
  - Asia: $1.5M Electronics, $700K Furniture, $800K Clothing

## Image Description
"The illustration depicts a globe highlighting trading routes between continents, with arrows marking the direction of trade flows. North America is shown trading heavily with Asia and Europe, represented by bold arrows."

## Formula
E = mc^2
(Energy equals mass times the square of the speed of light.)

## Flowchart Description
"The flowchart represents a decision-making process for a customer choosing a product:
1. Start at the 'Customer Needs' box.
2. Evaluate if the need is urgent or not.
3. If urgent: Proceed to 'Express Shipping.'
4. If not urgent: Proceed to 'Standard Shipping.'"

""",

    IndexingRole.METADATA_EXTRACT: """提取文章的基本信息(如作者、单位、发布日期等)

# 任务说明

- **提取基本信息**:识别文章的元信息,包括文章名字、作者姓名、单位或机构名称、发布日期等(如果数据存在于文章中)。

# 输出格式

- **基本信息**:输出为 JSON 格式,包含 `author`、`institution`、`publish_date` 等字段,若字段不存在可返回 `null`。

# 注意事项

- 若某些基本信息缺失,请在 JSON 中用 `null`标明,例如 `"author": null`。
""",

    IndexingRole.CHAPTER_EXTRACT: """解析文章内容,提取其目录结构,并返回一个标准的 JSON 风格列表,其中包含章节标题及对应的起始页码。

# 详细任务说明
1. **内容扫描**:
   - 扫描全文,识别章节标题。
   - 不要添加、总结或修改任何章节标题,保持与原文一致。

2. **层级与范围**:
   - 如果文章没有显示划分子目录但章节标题清晰,应按其显示逻辑提取。

3. **页码准确性**:
   - 提取每个章节标题的起始页码,确保与文章中标注的页码保持一致性。

4. **单层结构兼容**:
   - 如果文章无明显章节分隔,则将文章整体作为一个单条记录,标题设为全文内容的标题,起始页码为文章第一页。

# 输出格式

以 JSON 列表的方式返回,其中每个章节是一个对象,包含以下 key:
- `title`:章节标题。
- `page`:章节的起始页码。

# 输出规则
- 确保章节顺序与文章编排一致,无遗漏或重新组织。
- 无需额外标注文章标题、作者等非目录信息。

# 注意事项
- **一致性**:输出结构和格式必须始终符合上述 JSON 示范样式。
""",

    IndexingRole.SUB_CHAPTER_EXTRACT: """解析文章内容,提取其目录结构,并返回一个标准的 JSON 风格列表,其中包含章节标题及对应的起始页码。

# 详细任务说明
1. **内容扫描**:
   - 扫描全文,识别章节标题。
   - 提取文章中的目录标题。
   - 不要添加、总结或修改任何章节标题,保持与原文一致。

2. **层级与范围**:
   - 如果文章没有显示划分子目录但章节标题清晰,应按其显示逻辑提取。

3. **页码准确性**:
   - 提取每个章节标题的起始页码,确保与文章中标注的页码保持一致性。

4. **单层结构兼容**:
   - 如果文章无明显章节分隔,则将文章整体作为一个单条记录,标题设为全文内容的标题,起始页码为文章第一页。

# 输出格式

以 JSON 列表的方式返回,其中每个章节是一个对象,包含以下 key:
- `title`:章节标题。
- `page`:章节的起始页码。

# 输出规则
- 确保章节顺序与文章编排一致,无遗漏或重新组织。
- 无需额外标注文章标题、作者等非目录信息。

# 注意事项
- **一致性**:输出结构和格式必须始终符合上述 JSON 示范样式。
""",

    IndexingRole.CONTENT_SUMMARY: """对输入的文本内容进行总结和信息提取,确保尽可能保留关键的原始信息和结构。

**关键要求**:
1. 确保总结清晰且忠实于原文内容,无删减主要信息。
2. 对数据或者列表中的要点,按照原有顺序进行提取和缩写。
3. 针对长文本,可以按模块分段总结,每段保留对应的核心信息。

# Steps
1. 阅读和理解输入的文本内容。
2. 提取核心信息,包括数据、论点、或规定的上下文。
3. 对每一个模块进行分点或简明叙述,保留每段的内容关系和逻辑。
4. 输出的总体呈现可以继续维护文本长度的相对压缩度,但对专业术语避免删减。

# Output Format
1. 输出为分段总结,例如:
   - 如果文本逻辑有自然的章节/段落/子标题,按照原顺序分别提取每段的要点。
   - 如果没有明确逻辑,则直接按行或列表方式呈现。
2. 内容可以使用 Markdown 格式呈现,以便提升阅读性,例如:标题 (#)、列表 (-)、强调点子(**)。

# Examples
## 输入:
以下是一段复杂的用户给到的内容,[...]

## 输出:
```
### 标题/子主题 (如果有)
- 核心要点列出保持逻辑:
- [EXAMPLE PLACEHOLDER STRUCTURE ,...]
""",
}
