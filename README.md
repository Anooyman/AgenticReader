# AgenticReader

中文 | [English](README_EN.md)

AgenticReader 是一个基于大语言模型（LLM）的智能文档分析与问答工具。支持 PDF 和网页内容解析，集成多种 LLM 提供商（Azure OpenAI、OpenAI、Ollama），可自动提取内容、生成摘要、构建向量数据库并支持多轮智能问答。

---

## 核心特性 | Key Features

### 文档处理 | Document Processing
- **多格式支持**: PDF 文档和网页 URL 内容解析
- **智能提取**: PDF 转图片 + OCR，网页内容通过 MCP 服务获取
- **自动切分**: 根据内容长度智能切分文本
- **向量数据库**: 基于 FAISS 的高效语义检索

### 智能问答 | Intelligent Q&A
- **多轮对话**: 自动缓存历史检索内容，支持上下文连续对话
- **章节检索**: 推荐带章节名提问以提升检索效果
- **自动摘要**: 生成简要摘要（brief_summary）和详细摘要（detail_summary）
- **多格式导出**: 支持 Markdown 和 PDF 格式导出

### 多代理系统 | Multi-Agent System
- **智能记忆系统**: 基于多代理架构的记忆管理，支持智能存储和检索个人信息
- **PlanAgent**: 顶层协调器，分析查询、创建执行计划、评估结果
- **ExecutorAgent**: 中层执行器，管理子代理并协调计划执行
- **MemoryAgent**: 专用记忆代理，支持多维度标记（时间、地点、人物、标签）

### 现代化 Web 界面 | Modern Web Interface
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
- Node.js (可选，用于 MCP 服务)
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
mkdir -p data/pdf data/pdf_image data/json_data data/vector_db data/output data/memory data/sessions data/sessions/backups data/sessions/exports data/config

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

# 访问地址
# 主页: http://localhost:8000
# 数据管理: http://localhost:8000/data
# API 文档: http://localhost:8000/docs
# ReDoc: http://localhost:8000/redoc
```

#### 方式 2: 命令行模式
```bash
# 运行主程序
python main.py

# 根据提示选择：
# - 输入 PDF 文件名（如: paper.pdf）
# - 输入网页 URL（如: https://example.com/article）
# - 输入问题进行多轮对话
# - 输入 "退出"、"bye"、"exit" 等退出
```

---

<details>
<summary><b>💡 使用示例（点击展开）</b></summary>

### PDF 文档分析
```bash
# 1. 将 PDF 文件放入 data/pdf/ 目录
cp your_paper.pdf data/pdf/

# 2. 运行 main.py，输入文件名
python main.py
# 输入: your_paper.pdf

# 3. 系统自动处理并生成摘要
# 输出位置: data/output/your_paper/
#   - brief_summary.md / brief_summary.pdf
#   - detail_summary.md / detail_summary.pdf
```

### 网页内容分析
```bash
# 安装 MCP 服务（首次使用）
# 选项 1: Playwright MCP（推荐）
npx @playwright/mcp@latest

# 选项 2: DuckDuckGo MCP
uv pip install duckduckgo-mcp-server

# 运行并输入 URL
python main.py
# 输入: https://arxiv.org/abs/1706.03762
```

### 智能问答
```bash
# 提问示例（带章节名效果更好）
You: 请解释 Introduction 章节的核心观点
You: Abstract 中提到的主要贡献是什么？
You: 对比 Method 和 Conclusion 的内容
```

### Web 界面使用
1. **上传文档**: 点击上传 PDF 或输入 URL
2. **查看摘要**: 自动生成文档摘要和结构
3. **智能对话**: 在聊天框中提问，支持多轮对话
4. **会话管理**: 保存、导出、导入会话记录
5. **PDF 预览**: 在线查看 PDF 文档
6. **数据管理**: 查看和管理所有文档数据，支持细粒度删除

</details>

<details>
<summary><b>📊 数据管理功能（点击展开）</b></summary>

访问 `http://localhost:8000/data` 进入数据管理界面：

**功能特性:**
- **存储概览**: 实时查看文档数量、存储大小、会话统计
- **文档管理**: 每个文档显示详细的数据分类（JSON、向量数据库、图片、摘要）
- **部分删除**: 可单独删除某个文档的特定数据类型，如只删除图片保留其他数据
- **批量操作**: 支持多选文档批量删除
- **缓存管理**: 独立管理 PDF 图片缓存、向量数据库缓存、JSON 数据缓存
- **智能清理**: 自动清理超过 30 天的旧数据
- **数据备份**: 创建会话和配置的备份文件

**使用场景:**
- 释放磁盘空间：只删除大文件（图片）保留其他数据
- 重建索引：删除向量数据库后重新构建
- 更新摘要：删除旧摘要重新生成
- 定期维护：使用智能清理功能自动清理过期数据

</details>

---

<details>
<summary><b>📁 项目结构（点击展开）</b></summary>

```
AgenticReader/
├── main.py                    # CLI 程序入口
├── requirements.txt           # Python 依赖
├── CLAUDE.md                  # Claude Code 开发指南
├── README.md                  # 项目说明文档
├── LICENSE                    # 开源许可协议
│
├── src/
│   ├── config/                # 配置文件
│   │   ├── settings.py        # 主配置（LLM、MCP、路径）
│   │   ├── constants.py       # 常量定义
│   │   └── prompts/           # 提示词配置
│   │
│   ├── core/                  # 核心功能
│   │   ├── llm/               # LLM 客户端（支持多提供商）
│   │   ├── processing/        # 文本处理（分词、切分）
│   │   └── vector_db/         # 向量数据库（FAISS）
│   │
│   ├── readers/               # 文档读取器
│   │   ├── base.py            # 基础读取器类
│   │   ├── pdf.py             # PDF 读取器
│   │   └── web.py             # Web 读取器
│   │
│   ├── chat/                  # 多代理系统
│   │   ├── chat.py            # PlanAgent + ExecutorAgent
│   │   └── memory_agent.py    # 记忆代理
│   │
│   ├── services/              # 外部服务
│   │   └── mcp_client.py      # MCP 服务客户端
│   │
│   ├── ui/                    # Web 界面
│   │   ├── backend/           # FastAPI 后端
│   │   │   ├── app.py         # 主应用
│   │   │   ├── api/           # API 路由
│   │   │   │   └── v1/        # API v1版本
│   │   │   │       ├── data.py      # 数据管理API
│   │   │   │       ├── chat.py      # 聊天API
│   │   │   │       ├── pdf.py       # PDF处理API
│   │   │   │       └── web.py       # Web处理API
│   │   │   ├── services/      # 业务逻辑
│   │   │   │   ├── data_service.py  # 数据管理服务
│   │   │   │   └── session_service.py # 会话管理服务
│   │   │   └── models/        # 数据模型
│   │   ├── templates/         # Jinja2 模板
│   │   ├── static/            # 静态资源（CSS、JS）
│   │   │   └── js/
│   │   │       └── data.js    # 数据管理前端
│   │   └── run_server.py      # 服务器启动脚本
│   │
│   └── utils/                 # 工具函数
│
└── data/                      # 数据目录（运行时生成）
    ├── pdf/                   # PDF 文件存放
    ├── pdf_image/             # PDF 转图片缓存
    ├── json_data/             # 提取的内容 JSON
    ├── vector_db/             # 向量数据库文件
    ├── output/                # 生成的摘要文件
    ├── memory/                # 记忆系统数据
    └── sessions/              # Web 界面会话数据
        ├── backups/
        │   └── chat_sessions_current.json  # 当前会话
        └── exports/           # 导出的会话
```

</details>

---

<details>
<summary><b>🏗️ 技术架构（点击展开）</b></summary>

### 核心组件

1. **Reader System** (src/readers/)
   - ReaderBase: 抽象基类，提供通用处理流程
   - PDFReader: PDF 文档处理（PyMuPDF + OCR）
   - WebReader: 网页内容处理（MCP 服务）

2. **LLM Abstraction** (src/core/llm/)
   - 统一接口支持多提供商（Azure OpenAI、OpenAI、Ollama）
   - 角色化提示词管理
   - 会话上下文自动处理

3. **Vector Database** (src/core/vector_db/)
   - FAISS 向量存储
   - 语义相似度检索
   - 章节元数据管理

4. **Multi-Agent System** (src/chat/)
   - 基于 LangGraph 的状态图管理
   - 异步任务分解与协调
   - 智能记忆管理

5. **Web UI** (src/ui/)
   - FastAPI + WebSocket 实时通信
   - 会话持久化（双存储架构）
   - 数据管理系统（细粒度控制）
   - 模块化 API 设计

### 数据流

```
输入 (PDF/URL)
  → 内容提取
  → 文本切分
  → 章节检测
  → 内容总结
  → 向量化
  → 存储到 FAISS

用户提问
  → 章节检索
  → 上下文组装
  → LLM 生成回答
  → 返回用户
```

</details>

---

<details>
<summary><b>🔌 MCP 服务配置（点击展开）</b></summary>

AgenticReader 使用 MCP (Model Context Protocol) 服务扩展功能：

### Web 内容获取
```bash
# 选项 1: Playwright MCP（推荐）
npx @playwright/mcp@latest

# 选项 2: DuckDuckGo MCP
uv pip install duckduckgo-mcp-server
```

**配置位置**: `src/config/settings.py` → `MCP_CONFIG`
- 默认使用 DuckDuckGo
- 切换到 Playwright: 取消注释 `playwright` 部分（第 21-27 行）

### 记忆服务
```bash
# 安装 RAG Memory MCP
npm install -g rag-memory-mcp

# 或临时运行
npx -y rag-memory-mcp
```

</details>

---

<details>
<summary><b>🛠️ 开发指南（点击展开）</b></summary>

### 添加新的 LLM 提供商
1. 在 `src/core/llm/client.py` 中扩展 `LLMBase`
2. 在 `src/config/settings.py` 的 `LLM_CONFIG` 中添加配置
3. 更新提供商切换逻辑

### 添加新的代理
1. 继承 `GraphBase` 创建代理类
2. 实现 `build_graph()` 和核心处理方法
3. 在 `src/config/settings.py` 的 `AgentCard` 中添加配置
4. 在 `ExecutorAgent._create_agent()` 中处理新代理类型

### 扩展 Web API
1. 在 `src/ui/backend/api/v1/` 中创建新路由文件
2. 在 `src/ui/backend/app.py` 中注册路由
3. 遵循 RESTful 约定和 FastAPI 最佳实践

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

# 测试特定模块
python src/chat/memory_agent.py
python src/chat/chat.py
```

</details>

---

<details>
<summary><b>❓ 常见问题（点击展开）</b></summary>

### 1. PDF 文件未被识别？
- 确保文件已放入 `data/pdf/` 目录
- 检查文件名拼写是否正确
- 支持的格式: `.pdf`

### 2. LLM API 报错？
- 检查 `.env` 文件中的 API key 是否正确
- 验证 endpoint 和模型名称配置
- 确认账户有足够的额度

### 3. 向量数据库加载失败？
- 首次使用会自动创建，无需担心
- 如需重建: 删除 `data/vector_db/<文档名>` 文件夹后重新运行
- 或使用数据管理界面删除向量数据库

### 4. Web 界面无法启动？
```bash
# 检查依赖是否完整
pip install fastapi uvicorn jinja2 python-multipart websockets

# 检查端口是否被占用
lsof -i :8000

# 查看详细错误日志
python src/ui/run_server.py
```

### 5. MCP 服务连接失败？
- 确认 Node.js 已安装
- 检查 MCP 服务是否正确安装
- 查看 `src/config/settings.py` 中的 MCP 配置

### 6. 会话数据丢失？
- 检查 `data/sessions/backups/` 目录下的备份文件
- 使用 Web 界面的导入功能恢复备份
- 备份文件按时间戳命名，最多保留10个

### 7. 如何切换 LLM 提供商？
```python
# 在代码中指定
from src.readers.pdf import PDFReader
pdf_reader = PDFReader(provider="azure")  # 或 "openai", "ollama"

# 默认使用 openai（见 src/readers/base.py:35）
```

### 8. 如何清理旧数据释放空间？
- 访问 `http://localhost:8000/data` 进入数据管理界面
- 使用"智能清理"功能自动清理30天前的数据
- 或手动选择文档，删除特定数据类型（如只删除图片）

### 9. 误删数据如何恢复？
- 会话数据可以从 `data/sessions/backups/` 恢复
- 文档数据建议定期使用"数据备份"功能
- 备份文件保存在 `data/backups/` 目录

</details>

---

## 更新日志 | Changelog

### 2025-11-19 - 数据管理系统
- ✨ **新增数据管理界面** 
  - 实时存储概览仪表板（文档数量、存储大小、会话统计）
  - 文档详细信息展示（JSON、Vector DB、Images、Summary 独立显示）
  - **细粒度部分删除功能** - 可单独删除某个文档的特定数据类型
  - 批量选择和删除操作
  - 缓存管理（PDF图片、向量数据库、JSON数据独立管理）
  - 智能清理（自动清理超过N天的旧数据）
  - 数据备份和完全重置功能
- 📊 **新增服务层**
  - `DataService` - 文件系统操作和数据管理逻辑
  - 支持会话格式兼容性处理
- 🎨 **前端优化**

### 2025-11-05 - Web界面重构
- 新增 FastAPI + WebSocket 现代化 Web 界面
- 实现会话持久化管理和双存储架构
- 集成 PDF 在线查看器
- 添加自动备份和导入导出功能

### 2025-09-05 - 多代理系统
- 新增智能记忆系统（Memory Agent）
- 实现多代理系统架构（PlanAgent + ExecutorAgent）
- 支持多维度记忆管理（时间、地点、人物、标签）
- 基于 LangGraph 工作流

### 2025-07-30 - Web Reader
- 新增 Web Reader 功能
- 支持通过 URL 解析网页内容
- 集成 MCP 服务

### 2025-07-23 - 摘要导出
- 新增摘要文件导出功能
- 支持 Markdown 和 PDF 两种格式
- 新增 `save_data_flag` 控制参数

---

<details>
<summary><b>🤝 贡献指南（点击展开）</b></summary>

欢迎提交 Issue 和 Pull Request！

### 开发流程
1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

### 代码规范
- 遵循 PEP 8 Python 代码风格
- 添加必要的注释和文档字符串
- 确保所有测试通过
- 更新相关文档

</details>

---

## 许可协议 | License

本项目采用 MIT License 开源协议。详见 [LICENSE](LICENSE) 文件。

---

## 致谢 | Acknowledgements

- [LangChain](https://github.com/langchain-ai/langchain) - LLM 应用开发框架
- [LangGraph](https://github.com/langchain-ai/langgraph) - 多代理状态图管理
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化 Web 框架
- [FAISS](https://github.com/facebookresearch/faiss) - 高效向量检索
- [PyMuPDF](https://pymupdf.readthedocs.io/) - PDF 处理
- [Model Context Protocol](https://modelcontextprotocol.io/) - MCP 服务

---

## 联系方式 | Contact

如有问题或建议，请通过以下方式联系：
- 提交 GitHub Issue
- 发起 Discussion

---

**⭐ 如果这个项目对您有帮助，欢迎给个 Star！**
