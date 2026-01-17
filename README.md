# AgenticReader

中文 | [English](README_EN.md)

AgenticReader 是一个基于大语言模型（LLM）和多智能体架构（Multi-Agent）的智能文档分析与问答工具。采用 Agent 编排模式，支持 PDF 文档解析，集成多种 LLM 提供商（Azure OpenAI、OpenAI、Ollama），可自动提取内容、生成摘要、构建向量数据库并支持多轮智能问答。

---

## 核心特性 | Key Features

### 🤖 多智能体架构 | Multi-Agent System
- **IndexingAgent**: 文档索引代理，负责 PDF 解析、结构提取、分块、向量化
- **AnswerAgent**: 问答代理，负责意图分析、答案生成、对话管理
- **RetrievalAgent**: 检索代理，负责语义检索和上下文组装
- **LangGraph 编排**: 基于 LangGraph 的状态机工作流，支持复杂任务编排

### 📄 文档处理 | Document Processing
- **智能索引**: PDF 转图片 + OCR 提取内容
- **结构分析**: 自动检测文档目录和章节结构
- **分块处理**: 智能文本分块，支持章节级别组织
- **向量数据库**: 基于 FAISS 的高效语义检索
- **并行处理**: 异步并行处理章节，大幅提升处理速度
- **增量缓存**: 支持各阶段缓存，避免重复处理

### 💬 智能问答 | Intelligent Q&A
- **意图识别**: 自动判断是否需要检索文档
- **上下文管理**: 智能缓存检索结果，支持多轮对话
- **历史压缩**: LLM 自动总结对话历史，节省上下文空间（90%+ 压缩率）
- **文档摘要**: 自动生成简要摘要（brief_summary.md）
- **多文档支持**: 可在多个已索引文档间切换

### 🌐 现代化 Web 界面 | Modern Web Interface
- **FastAPI + WebSocket**: 实时聊天通信
- **会话持久化**: 自动保存、备份轮换（保留最近 10 个）、导入导出
- **双存储架构**: 客户端 localStorage + 服务端文件存储
- **PDF 查看器**: 集成 PDF 在线预览，支持页面导航
- **数据管理系统**: 细粒度数据管理，支持部分删除、批量操作、智能清理
- **响应式设计**: 移动端友好的自适应界面

---

## 快速开始 | Quick Start

### 环境要求 | Requirements
- Python 3.12+
- 虚拟环境（推荐）

<details>
<summary><b>📦 安装配置（点击展开）</b></summary>

### 安装步骤

```bash
# 1. 克隆项目
git clone <repository-url>
cd AgenticReader

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 创建数据目录
mkdir -p data/pdf data/pdf_image data/json_data data/vector_db data/output data/sessions data/sessions/backups data/sessions/exports

# 4. 配置环境变量（创建 .env 文件）
# 参考下方"配置说明"部分
```

### 配置说明

在项目根目录创建 `.env` 文件：

```bash
# === LLM 服务配置 ===
# Azure OpenAI
CHAT_API_KEY=your_azure_api_key
CHAT_AZURE_ENDPOINT=https://your-endpoint.openai.azure.com/
CHAT_DEPLOYMENT_NAME=your_deployment_name
CHAT_API_VERSION=2024-02-15-preview
CHAT_MODEL_NAME=gpt-4

# Embedding 配置
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_MODEL=text-embedding-ada-002

# === 或使用 OpenAI ===
# CHAT_API_KEY=your_openai_api_key
# CHAT_MODEL_NAME=gpt-4
# OPENAI_BASE_URL=https://api.openai.com/v1/

# === 或使用 Ollama (本地) ===
# OLLAMA_BASE_URL=http://localhost:11434
# CHAT_MODEL_NAME=llama3

# === 可选配置 ===
LOGGING_LEVEL=INFO
```

</details>

### 运行应用 | Running the Application

#### 方式 1: Web 界面（推荐）
```bash
# 启动 FastAPI 服务器
python src/ui/run_server.py

# 或使用 uvicorn（支持自动重载）
uvicorn src.ui.backend.app:app --reload --host 0.0.0.0 --port 8000

# 访问 Web 界面
# http://localhost:8000
```

**Web 界面功能：**
- 📄 **PDF 处理**: 上传PDF → 自动索引 → 开始聊天
- 💬 **智能对话**: 多轮问答、历史管理、会话切换
- 📊 **数据管理**: 查看存储占用、删除文档数据、智能清理
- ⚙️ **配置管理**: 切换 LLM 提供商、调整参数

#### 方式 2: CLI 模式
```bash
# 交互式命令行界面
python main.py

# 流程:
# 1. 选择或索引文档
# 2. 开始对话
# 3. 输入问题，AI 自动检索并回答
```

---

<details>
<summary><b>📂 项目结构（点击展开）</b></summary>

```
AgenticReader/
├── main.py                        # CLI 入口（使用 AnswerAgent）
├── src/
│   ├── agents/                    # 🤖 多智能体系统
│   │   ├── indexing/              # IndexingAgent - 文档索引
│   │   │   ├── agent.py           # 索引代理实现
│   │   │   ├── state.py           # 索引状态定义
│   │   │   └── doc_registry.py    # 文档注册表
│   │   ├── answer/                # AnswerAgent - 智能问答
│   │   │   ├── agent.py           # 问答代理实现
│   │   │   └── state.py           # 问答状态定义
│   │   └── retrieval/             # RetrievalAgent - 文档检索
│   │       ├── agent.py           # 检索代理实现
│   │       └── state.py           # 检索状态定义
│   ├── core/                      # 核心功能
│   │   ├── llm/                   # LLM 抽象层
│   │   │   ├── client.py          # 统一 LLM 客户端
│   │   │   ├── providers.py       # 多提供商支持
│   │   │   └── history.py         # 对话历史管理
│   │   ├── vector_db/             # 向量数据库
│   │   │   └── vector_db_client.py
│   │   └── processing/            # 文档处理工具
│   │       ├── index_document.py  # 文档索引入口
│   │       ├── manage_documents.py # 文档管理工具
│   │       ├── parallel_processor.py # 并行处理器
│   │       └── text_splitter.py   # 文本分割器
│   ├── config/                    # 配置管理
│   │   ├── settings.py            # 全局配置
│   │   ├── prompts/               # 提示词模板
│   │   └── tools/                 # Agent 工具定义
│   ├── services/                  # 外部服务
│   │   └── mcp_client.py          # MCP 客户端（保留）
│   ├── ui/                        # Web 界面
│   │   ├── run_server.py          # FastAPI 启动脚本
│   │   ├── backend/               # 后端 API
│   │   │   ├── app.py             # FastAPI 应用
│   │   │   ├── api/v1/            # API 端点
│   │   │   │   ├── pdf.py         # PDF 处理（使用 IndexingAgent）
│   │   │   │   ├── chapters.py    # 章节查看
│   │   │   │   ├── chat.py        # WebSocket 聊天
│   │   │   │   └── data.py        # 数据管理
│   │   │   └── services/          # 服务层
│   │   │       ├── chat_service.py # 聊天服务（使用 AnswerAgent）
│   │   │       ├── session_service.py # 会话管理
│   │   │       └── data_service.py    # 数据管理
│   │   ├── templates/             # Jinja2 模板
│   │   └── static/                # 静态资源
│   └── utils/                     # 工具函数
├── data/                          # 数据目录
│   ├── pdf/                       # PDF 源文件
│   ├── pdf_image/                 # PDF 转图片
│   ├── json_data/                 # 文档数据（按文档名分文件夹）
│   │   └── {doc_name}/            # 文档数据文件夹
│   │       ├── data.json          # 原始提取数据
│   │       ├── structure.json     # 文档结构
│   │       └── chunks.json        # 分块数据
│   ├── vector_db/                 # 向量数据库
│   ├── output/                    # 生成的摘要文件
│   ├── sessions/                  # 会话数据
│   │   ├── backups/               # 会话备份
│   │   └── exports/               # 会话导出
│   └── doc_registry.json          # 文档注册表
└── requirements.txt               # Python 依赖
```

</details>

---

<details>
<summary><b>🏗️ 技术架构（点击展开）</b></summary>

### 核心组件

1. **Multi-Agent System** (src/agents/)
   - **IndexingAgent**: 文档索引工作流
     - 解析 PDF → 提取结构 → 分块 → 并行处理 → 向量化 → 注册
   - **AnswerAgent**: 智能问答工作流
     - 意图分析 → 检索决策 → 答案生成 → 结果评估
   - **RetrievalAgent**: 文档检索工作流
     - 语义检索 → 上下文组装 → 结果排序

2. **LLM Abstraction** (src/core/llm/)
   - 统一接口支持多提供商（Azure OpenAI、OpenAI、Ollama）
   - 角色化提示词管理
   - 会话上下文自动处理
   - 对话历史智能压缩

3. **Vector Database** (src/core/vector_db/)
   - FAISS 向量存储
   - 语义相似度检索
   - 章节元数据管理
   - 自动加载已有索引

4. **Document Registry** (src/agents/indexing/doc_registry.py)
   - 集中管理所有文档元数据
   - 跟踪处理阶段状态
   - 记录生成文件路径
   - 支持增量索引

5. **Web UI** (src/ui/)
   - FastAPI + WebSocket 实时通信
   - 基于 AnswerAgent 的聊天服务
   - 基于 IndexingAgent 的文档处理
   - 数据管理系统（细粒度控制）

### Agent 工作流

#### IndexingAgent 工作流
```
PDF 文件
  → check_cache (检查各阶段缓存)
  → parse_document (解析 PDF)
  → extract_structure (提取文档结构)
  → chunk_text (文本分块)
  → process_chapters (并行处理章节)
  → build_index (构建向量数据库)
  → generate_brief_summary (生成摘要)
  → register_document (注册到 DocumentRegistry)
```

#### AnswerAgent 工作流
```
用户提问
  → analyze_intent (意图分析)
  → retrieve_if_needed (条件检索)
  → generate_answer (生成答案)
  → evaluate_result (评估完整性)
  → 返回用户
```

### 数据存储架构

**JSON 数据**（按文档组织）:
```
data/json_data/{doc_name}/
├── data.json           # 原始提取数据
├── structure.json      # 文档结构信息
└── chunks.json         # 分块数据
```

**优势**:
- 📁 所有 JSON 文件集中在文档文件夹中
- 🗑️ 删除时直接删除整个文件夹，不会遗漏文件
- 🔍 易于查找和管理特定文档的数据

</details>

---

<details>
<summary><b>🛠️ 开发指南（点击展开）</b></summary>

### 添加新的 LLM 提供商
1. 在 `src/core/llm/providers.py` 中添加提供商实现
2. 在 `src/config/settings.py` 的 `LLM_CONFIG` 中添加配置
3. 更新提供商切换逻辑

### 添加新的 Agent
1. 在 `src/agents/` 下创建新 agent 目录
2. 创建 `agent.py` (继承 AgentBase) 和 `state.py` (定义 TypedDict)
3. 实现 `build_graph()` 方法定义工作流
4. 在其他 Agent 中集成调用

### 扩展 IndexingAgent
1. 在 `agent.py` 中添加新的处理节点
2. 在 `build_graph()` 中连接新节点
3. 更新 `IndexingState` 添加新字段
4. 实现缓存检查逻辑

### 扩展 Web API
1. 在 `src/ui/backend/api/v1/` 中创建新路由文件
2. 使用 Agent 而不是直接调用处理逻辑
3. 在 `src/ui/backend/app.py` 中注册路由
4. 遵循 RESTful 约定和 FastAPI 最佳实践

### 扩展数据管理功能
1. 在 `DataService.delete_document_data()` 中添加新数据类型
2. 更新 `data_type_paths` 字典映射
3. 在 API 中添加对应端点
4. 在前端 `renderDataDetail()` 中显示新类型

### 调试技巧
```bash
# 启用 DEBUG 日志
export LOGGING_LEVEL=DEBUG
python main.py

# FastAPI 开发模式（自动重载）
uvicorn src.ui.backend.app:app --reload --host 0.0.0.0 --port 8000

# 查看 API 文档
# http://localhost:8000/docs

# 测试 Agent
python -c "from src.agents.indexing import IndexingAgent; print('OK')"
python -c "from src.agents.answer import AnswerAgent; print('OK')"
```

</details>

---

<details>
<summary><b>❓ 常见问题（点击展开）</b></summary>

### 1. PDF 文件未被识别？
- 确保文件已放入 `data/pdf/` 目录
- 检查文件名拼写是否正确
- 支持的格式: `.pdf`

### 2. 索引失败怎么办？
- 检查 LLM API 配置是否正确
- 确认网络连接正常
- 查看日志输出定位错误
- 尝试使用 `LOGGING_LEVEL=DEBUG` 查看详细信息

### 3. 对话历史如何管理？
- 由 `LLMBase.message_histories` 自动管理
- LLM 会自动总结历史以节省上下文
- Web 界面支持查看和清空历史

### 4. 如何查看已索引的文档？
```bash
# CLI 模式
python main.py
# 选择 'm' 进入文档管理

# Web 模式
访问 http://localhost:8000/data
```

### 5. 如何删除文档？
```bash
# CLI 模式
python -m src.core.processing.manage_documents

# Web 模式
访问 http://localhost:8000/data
# 使用细粒度删除功能
```

### 6. 会话数据丢失如何恢复？
- 访问 `data/sessions/backups/` 目录
- 使用 Web 界面的导入功能恢复备份
- 备份文件按时间戳命名，最多保留10个

### 7. 如何切换 LLM 提供商？
```bash
# 修改 .env 文件
CHAT_API_KEY=your_api_key
CHAT_MODEL_NAME=your_model

# 或在 Web 界面的配置页面切换
```

### 8. 如何清理旧数据释放空间？
- 访问 `http://localhost:8000/data` 进入数据管理界面
- 使用"智能清理"功能自动清理30天前的数据
- 或手动选择文档，删除特定数据类型（如只删除图片）

### 9. 误删数据如何恢复？
- 会话数据可以从 `data/sessions/backups/` 恢复
- 文档数据建议定期使用"数据备份"功能
- 备份文件保存在 `data/backups/` 目录

### 10. IndexingAgent vs 旧的 Reader？
- ✅ **IndexingAgent** (新): 基于 LangGraph 的状态机工作流，支持缓存、增量处理、阶段跟踪
- ❌ **PDFReader/WebReader** (已移除): 旧的类继承架构，已完全移除

</details>

---

<details>
<summary><b>📝 更新日志 | Changelog（点击展开）</b></summary>

### 2026-01-17 - 架构大重构：迁移到 Multi-Agent 系统
- 🏗️ **架构重构**
  - ✅ 完全移除旧的 Reader 架构（PDFReader, WebReader, ReaderBase）
  - ✅ 所有功能迁移到 Multi-Agent 架构（IndexingAgent, AnswerAgent, RetrievalAgent）
  - ✅ 基于 LangGraph 的状态机工作流编排
  - ✅ UI 后端迁移到使用 Agent（chat_service.py 使用 AnswerAgent，pdf.py 使用 IndexingAgent）
  - ✅ 删除 `src/readers/` 目录，parallel_processor 移至 `src/core/processing/`
  - ✅ 简化 chapters.py，暂时移除章节编辑功能
- 📁 **数据存储优化**
  - ✅ JSON 文件按文档组织：`data/json_data/{doc_name}/data.json`
  - ✅ 统一管理文档的所有 JSON 文件（data.json, structure.json, chunks.json）
  - ✅ 删除文档时直接删除整个文件夹，不会遗漏文件
- 🔄 **状态管理增强**
  - ✅ IndexingState 新增 `is_complete` 字段跟踪完成状态
  - ✅ DocumentRegistry 自动创建临时记录跟踪处理进度
  - ✅ 各阶段缓存检查，避免重复处理
- 🗑️ **代码精简**
  - ❌ 删除 Web 相关 API 和后端代码（暂时，待重新设计）
  - ❌ 删除约 1500+ 行旧 Reader 代码
  - ✅ 保留 MCP 客户端（按要求）
  - ✅ 代码库更清晰，易于维护

### 2025-11-26 - 并行处理优化和章节管理界面
- ⚡ **并行处理优化**
  - 新增 `src/utils/async_utils.py` - 通用异步并行处理工具
  - 新增 `src/core/processing/parallel_processor.py` - 专用并行处理器
  - 章节总结和内容重构并行执行，处理速度提升 3-5 倍
  - 详细摘要生成并行化，支持信号量控制并发数
- 📁 **独立章节管理界面**
  - 新增 `/chapters` 页面 - 与配置管理、数据管理并列
  - 集成 PDF 预览功能，左侧章节列表 + 右侧 PDF 显示
  - 支持章节编辑、添加、删除操作
  - 支持批量重建向量数据库和摘要
  - 处理过程进度提示和章节高亮显示
- 🛠️ **代码重构**
  - 将并行处理逻辑抽取为独立模块，提高代码复用性

### 2025-11-19 - 数据管理系统
- ✨ **新增数据管理界面**
  - 实时存储概览仪表板（文档数量、存储大小、会话统计）
  - 文档详细信息展示（JSON、Vector DB、Images、Summary 独立显示）
  - **细粒度部分删除功能** - 可单独删除某个文档的特定数据类型
  - 批量操作支持 - 一次选择多个文档删除
  - 缓存管理 - 查看和清理 PDF 图片、向量 DB、JSON 缓存
  - 智能清理 - 自动删除指定天数前的旧数据
  - 数据备份功能 - 创建会话、输出、配置备份
  - 会话统计信息 - 总会话数、消息数、最近活动、备份数量

### 2025-10-31 - 会话系统增强
- 🔄 **会话持久化优化**
  - 双存储架构：客户端 localStorage + 服务端文件存储
  - 自动备份轮换机制（保留最近 10 个备份）
  - 会话导入/导出功能
  - 存储位置迁移：`chat_sessions.json` → `sessions/backups/chat_sessions_current.json`
- 🛠️ **后端优化**
  - SessionManager 重构，支持备份管理
  - 会话格式兼容性处理（支持 dict 和 list 两种格式）
  - 自动迁移旧会话文件

### 2025-09-15 - FastAPI Web 界面
- 🌐 **全新 Web 界面**
  - FastAPI + WebSocket 实时聊天
  - Jinja2 模板 + Vanilla JavaScript
  - PDF 在线预览集成
  - 响应式设计，移动端友好

### 2025-08-20 - 历史压缩优化
- 🧠 **智能历史管理**
  - LLM 自动总结对话历史
  - 90%+ 压缩率，显著节省 token
  - 保持上下文连贯性

### 2025-07-30 - Web Reader
- 新增 Web Reader 功能
- MCP 服务集成

</details>

---

## 许可证 | License

[MIT License](LICENSE)

## 贡献 | Contributing

欢迎提交 Issue 和 Pull Request！

## 致谢 | Acknowledgments

- [LangChain](https://github.com/langchain-ai/langchain) - 强大的 LLM 应用开发框架
- [LangGraph](https://github.com/langchain-ai/langgraph) - 多智能体编排框架
- [FAISS](https://github.com/facebookresearch/faiss) - 高效的向量检索库
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化的 Web 框架
