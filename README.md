# AgenticReader

中文 | [English](README_EN.md)

AgenticReader 是一个基于大语言模型（LLM）和多智能体架构（Multi-Agent）的智能文档分析与问答工具。采用 Agent 编排模式，专注于 **PDF 文档深度解析**，集成多种 LLM 提供商（Azure OpenAI、OpenAI、Ollama、Gemini），可自动提取内容、生成摘要、构建向量数据库并支持多轮智能问答。提供 **CLI 命令行** 和 **Web 界面** 两种使用方式。

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
- **四种对话模式**:
  - 单文档深度对话（Single）- 针对特定文档的深入问答
  - 跨文档智能对话（Cross）- 自动选择相关文档进行检索
  - 跨文档手动选择（Manual）- 手动指定多个文档作为背景知识
  - 通用对话模式（General）- 不绑定特定文档的自由对话
- **意图识别**: 自动判断是否需要检索文档
- **上下文管理**: 智能缓存检索结果，支持多轮对话
- **历史压缩**: LLM 自动总结对话历史，节省上下文空间（90%+ 压缩率）
- **文档摘要**: 自动生成简要摘要（brief_summary.md）

### 🌐 双模式操作 | Dual Operation Modes
- **CLI 命令行模式**:
  - 交互式菜单系统，支持文档索引、管理、对话
  - 四种对话模式自由切换
  - 实时查看文档选择和检索过程
  - 适合技术用户和自动化场景
- **Web 界面模式**:
  - **仪表板**: 文档概览、快速索引、模式选择
  - **智能聊天**: WebSocket 实时通信，支持 Markdown/LaTeX 渲染
  - **实时进度可视化**: 
    - 📊 **节点流程图**: 可视化展示 Agent 执行流程（改写→思考→执行→评估→输出）
    - 🔄 **迭代进度**: 实时显示检索迭代次数和百分比
    - 🛠️ **工具调用**: 展示当前使用的检索工具和详细信息
    - 🎨 **现代化设计**: 渐变背景、平滑动画、微交互效果
  - **并行检索可视化**:
    - 📚 **多文档并发**: 跨文档模式下同时展示所有文档的检索进度
    - 🔽 **折叠/展开**: 每个文档独立的进度卡片，可折叠查看详细流程
    - ⚡ **增量更新**: 无闪烁的实时更新，不打断用户查看
    - 🎯 **独立流程**: 每个 PDF 拥有独立的节点流程可视化
  - **会话管理**: 三种模式独立会话存储，支持导入/导出
  - **数据管理**: 细粒度数据控制，支持部分删除、批量操作、智能清理
  - **配置中心**: LLM 提供商切换、参数调整
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

# === 或使用 Gemini (Google) ===
# GEMINI_API_KEY=your_gemini_api_key
# GEMINI_MODEL_NAME=gemini-1.5-pro
# GEMINI_EMBEDDING_MODEL=text-embedding-004
# GEMINI_BASE_URL=your_gemini_api_endpoint

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

**Web 界面页面说明：**

<details>
<summary><b>📊 仪表板 (/) - 主菜单</b></summary>

- 文档列表展示（已索引文档概览）
- 快速索引入口（批量/单个文档）
- 模式选择（Single/Cross/Manual）
- 快速进入聊天页面
</details>

<details>
<summary><b>💬 聊天页面 (/chat) - 智能对话</b></summary>

**三种聊天模式：**
- **Single 单文档模式**: 选择特定文档进行深度问答
- **Cross 跨文档智能模式**: 自动选择相关文档进行检索（系统智能决策）
- **Manual 跨文档手动模式**: 手动指定多个文档作为背景知识

**功能特性：**
- WebSocket 实时通信，即时响应
- Markdown 和 LaTeX 公式渲染
- 时间戳显示（年/月/日 时:分:秒）
- 会话持久化存储（三种模式独立管理）
- 清空历史功能（同时清空文件和内存）
- 显示选中文档和相似度评分

**使用流程：**
1. 选择对话模式（Single/Cross/Manual）
2. 根据模式选择/指定文档
3. 开始对话，系统自动检索和回答
4. 支持多轮对话，上下文自动管理
</details>

<details>
<summary><b>📁 数据管理 (/data) - 文档和会话管理</b></summary>

**文档管理：**
- 查看所有已索引文档和存储占用
- **细粒度部分删除**：可单独删除某个文档的特定数据类型
  - JSON 数据（解析后的文档内容）
  - Vector DB（向量数据库索引）
  - Images（PDF 转换的图片文件）
  - Summary（生成的摘要文件）
- 批量操作：一次选择多个文档删除
- 智能清理：自动清理指定天数前的旧数据（默认 30 天）

**会话管理：**
- 查看所有模式的会话列表（Single/Cross/Manual）
- 会话详情查看（支持 Markdown/LaTeX 渲染）
- 删除特定会话
- 会话统计信息（总数、消息数、最近活动）
- 导入/导出会话数据

**存储概览：**
- 实时统计：文档数量、存储大小、会话数、备份数
- 数据备份功能（会话、输出、配置）
- 缓存管理（PDF 图片、Vector DB、JSON 数据）
</details>

<details>
<summary><b>⚙️ 配置中心 (/config) - LLM 配置管理</b></summary>

- 切换 LLM 提供商（Azure OpenAI、OpenAI、Ollama、Gemini）
- 调整模型参数（temperature、max_tokens 等）
- 配置 Embedding 模型
- API Key 管理
- 系统设置
</details>

<details>
<summary><b>🔧 结构编辑器 (/structure) - 文档结构管理</b></summary>

- 查看和编辑文档章节结构
- PDF 在线预览
- 章节元数据编辑
- 批量重建向量数据库
</details>

---

#### 方式 2: CLI 命令行模式

```bash
# 启动交互式命令行界面
python main.py
```

**CLI 主菜单选项：**

<details>
<summary><b>点击查看 CLI 详细使用说明</b></summary>

**文档选择阶段：**
```
主菜单
═══════════════════════════════════════════════════════════════════════════
📚 已索引的文档：

  [1] document1.pdf
      这是第一个文档的简要摘要...

  [2] document2.pdf
      这是第二个文档的简要摘要...

请选择操作：
  [1-N] 选择文档进行单文档对话（Single 模式）
  [c] 跨文档智能对话（Cross 模式 - 自动选择相关文档）
  [s] 跨文档手动选择模式（Manual 模式 - 手动指定多个文档）
  [0] 通用对话模式（General 模式 - 不绑定特定文档）
  [i] 索引新文档
  [m] 管理文档（查看/删除）
  [q] 退出
```

**四种对话模式说明：**

1. **Single 模式 - 单文档深度对话**
   ```
   选择: 1
   ✅ 已选择文档: document1.pdf
   🔧 初始化 AnswerAgent（单文档模式: document1.pdf）...

   [单文档 (document1.pdf)] 👤 Query: 这个文档讲了什么？
   🤖 Assistant: 这个文档主要讲述了...
   ```
   - 专注于单个文档的深入问答
   - 所有检索都限定在选中的文档内
   - 适合深度学习和理解特定文档

2. **Cross 模式 - 跨文档智能对话**
   ```
   选择: c
   ✅ 已进入跨文档智能对话模式

   [跨文档模式] 👤 Query: 比较这两个文档的观点
   📚 选择的文档 (2 个):
      - document1.pdf (相似度: 0.856)
      - document2.pdf (相似度: 0.742)
   🤖 Assistant: 根据检索结果，这两个文档的主要观点...
   ```
   - 系统自动选择与问题最相关的文档
   - 支持跨文档比较和综合分析
   - 适合探索性研究和多文档对比

3. **Manual 模式 - 跨文档手动选择**
   ```
   选择: s

   手动选择文档
   ═══════════════════════════════════════════════════════════════════════════
   📚 可用文档列表:

     [1] document1.pdf
         这是第一个文档的简要摘要...

     [2] document2.pdf
         这是第二个文档的简要摘要...

     [3] document3.pdf
         这是第三个文档的简要摘要...

   💡 提示：
      - 输入文档编号，用逗号或空格分隔（例如: 1,3,5 或 1 3 5）
      - 输入 'all' 选择所有文档
      - 输入 'cancel' 取消选择

   请选择文档编号: 1,2

   ✅ 已选择 2 个文档:
      1. document1.pdf
      2. document2.pdf

   确认选择？(y/n): y

   [手动选择 (2 个文档)] 👤 Query: 总结这两个文档的核心内容
   📚 检索的文档 (2 个):
      - document1.pdf
      - document2.pdf
   🤖 Assistant: 综合两个文档的内容...
   ```
   - 手动指定要使用的文档
   - 适合明确知道需要哪些文档的场景
   - 支持多文档综合回答

4. **General 模式 - 通用对话**
   ```
   选择: 0
   ✅ 已进入通用对话模式（不绑定特定文档）

   [通用模式] 👤 Query: 什么是机器学习？
   🤖 Assistant: 机器学习是人工智能的一个分支...
   ```
   - 不依赖任何文档的自由对话
   - 纯粹的 LLM 对话能力
   - 适合通用问题和闲聊

**对话中的命令：**
- `clear` - 清除对话历史和上下文
- `switch` - 切换到其他对话模式
- `main` - 返回主菜单
- `quit` / `exit` - 退出程序

**文档管理（选择 m）：**
```
文档管理
═══════════════════════════════════════════════════════════════════════════
已索引的文档:

  [1] document1.pdf (125.5 MB)
  [2] document2.pdf (89.2 MB)

  [0] 返回主菜单

请选择要管理的文档编号: 1

文档详情:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📄 文档名称: document1.pdf
📊 数据类型:
   - JSON 数据: 2.5 MB
   - Vector DB: 45.8 MB
   - Images: 75.2 MB
   - Summary: 2.0 MB
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

管理选项:
  [d] 删除此文档及所有相关数据
  [b] 返回文档列表

请选择操作: d
确认删除？(y/n): y
✅ 文档 document1.pdf 已成功删除
```

**文档索引（选择 i）：**
```
启动文档索引工具...

可用的 PDF 文件：
  [1] new_document.pdf
  [2] another_document.pdf

选择要索引的文件（输入编号）: 1

开始索引 new_document.pdf...
✅ [Parse] 解析PDF完成
✅ [Structure] 提取文档结构完成
✅ [Chunk] 文本分块完成
✅ [Process] 并行处理章节完成
✅ [Index] 构建向量数据库完成
✅ [Summary] 生成摘要完成
✅ [Register] 注册到文档库完成

✅ 索引完成！
```

</details>

---

---

<details>
<summary><b>📂 项目结构（点击展开）</b></summary>

```
AgenticReader/
├── main.py                        # CLI 入口（支持4种对话模式）
├── src/
│   ├── agents/                    # 🤖 多智能体系统（完全模块化）
│   │   ├── base.py                # AgentBase 基类
│   │   ├── common/                # 共享模块
│   │   │   ├── prompts.py         # 通用提示词
│   │   │   └── __init__.py
│   │   ├── indexing/              # IndexingAgent（文档索引代理）
│   │   │   ├── agent.py           # 索引代理实现
│   │   │   ├── nodes.py           # 工作流节点
│   │   │   ├── tools.py           # 索引工具
│   │   │   ├── state.py           # 状态定义（TypedDict）
│   │   │   ├── prompts.py         # 索引专用提示词
│   │   │   ├── utils.py           # 辅助函数
│   │   │   └── __init__.py
│   │   ├── answer/                # AnswerAgent（问答代理）
│   │   │   ├── agent.py           # 问答代理实现
│   │   │   ├── nodes.py           # 工作流节点
│   │   │   ├── tools.py           # 问答工具
│   │   │   ├── state.py           # 状态定义（TypedDict）
│   │   │   ├── prompts.py         # 问答专用提示词
│   │   │   ├── tools_config.py    # 工具配置
│   │   │   ├── components/        # 组件模块
│   │   │   │   ├── coordinator.py # 跨文档协调器
│   │   │   │   ├── synthesizer.py # 答案综合器
│   │   │   │   └── formatter.py   # 答案格式化
│   │   │   └── __init__.py
│   │   └── retrieval/             # RetrievalAgent（检索代理）
│   │       ├── agent.py           # 检索代理实现
│   │       ├── nodes.py           # 工作流节点
│   │       ├── tools.py           # 检索工具
│   │       ├── state.py           # 状态定义（TypedDict）
│   │       ├── prompts.py         # 检索专用提示词
│   │       ├── tools_config.py    # 工具配置
│   │       └── __init__.py
│   ├── core/                      # 核心功能
│   │   ├── llm/                   # LLM 抽象层
│   │   │   ├── client.py          # 统一 LLM 客户端
│   │   │   ├── providers.py       # 多提供商支持（Azure/OpenAI/Ollama/Gemini）
│   │   │   ├── history.py         # 对话历史管理和压缩
│   │   │   └── __init__.py
│   │   ├── vector_db/             # 向量数据库
│   │   │   ├── vector_db_client.py # FAISS 向量存储
│   │   │   ├── metadata_db.py     # 元数据管理
│   │   │   └── __init__.py
│   │   ├── document_management/   # 文档管理（新增）
│   │   │   ├── registry.py        # 文档注册表（并发安全）
│   │   │   ├── indexer.py         # 文档索引器
│   │   │   ├── manager.py         # 文档管理器
│   │   │   └── __init__.py
│   │   ├── parallel/              # 并行处理
│   │   │   ├── processor.py       # 并行处理器
│   │   │   └── __init__.py
│   │   └── processing/            # 文档处理工具
│   │       ├── text_splitter.py   # 文本分割器
│   │       └── __init__.py
│   ├── config/                    # 配置管理
│   │   ├── settings.py            # 全局配置（LLM、Embedding、MCP）
│   │   ├── constants.py           # 常量定义
│   │   ├── prompts/               # 多代理协调提示词
│   │   │   ├── agent_prompts.py   # Plan/Executor/Memory Agent
│   │   │   └── metadata_prompts.py
│   │   └── __init__.py
│   ├── ui/                        # Web 界面（FastAPI）
│   │   ├── run_server.py          # FastAPI 启动脚本
│   │   ├── backend/               # 后端 API
│   │   │   ├── app.py             # FastAPI 应用入口
│   │   │   ├── config.py          # UI 配置
│   │   │   ├── api/               # API 路由
│   │   │   │   ├── pages.py       # 页面路由（/、/chat、/data、/config、/structure）
│   │   │   │   ├── websocket.py   # WebSocket 实时通信
│   │   │   │   └── v1/            # API v1 端点
│   │   │   │       ├── documents.py # 文档管理
│   │   │   │       ├── chat.py    # 聊天初始化
│   │   │   │       ├── pdf.py     # PDF 上传和索引
│   │   │   │       ├── chapters.py # 章节信息
│   │   │   │       ├── structure.py # 文档结构
│   │   │   │       ├── config.py  # 配置管理
│   │   │   │       ├── sessions.py # 会话管理（三种模式独立）
│   │   │   │       └── data.py    # 数据管理（细粒度删除）
│   │   │   └── services/          # 服务层
│   │   │       ├── chat_service.py # 聊天服务（使用 AnswerAgent）
│   │   │       └── session_manager.py # 会话管理器
│   │   ├── templates/             # Jinja2 模板
│   │   │   ├── base.html          # 基础模板
│   │   │   ├── dashboard.html     # 仪表板页面
│   │   │   ├── chat.html          # 聊天页面
│   │   │   ├── manage.html        # 数据管理页面
│   │   │   ├── config.html        # 配置页面
│   │   │   └── structure_editor.html # 结构编辑器
│   │   └── static/                # 静态资源
│   │       ├── css/               # 样式表
│   │       │   ├── variables.css  # CSS 变量
│   │       │   ├── base.css       # 基础样式
│   │       │   └── components.css # 组件样式
│   │       └── js/                # JavaScript
│   │           ├── dashboard.js   # 仪表板逻辑
│   │           ├── chat.js        # 聊天逻辑
│   │           ├── manage.js      # 数据管理逻辑
│   │           ├── config.js      # 配置逻辑
│   │           ├── api.js         # API 封装
│   │           ├── ui-components.js # UI 组件
│   │           └── utils.js       # 工具函数
│   └── utils/                     # 通用工具函数
├── data/                          # 数据目录
│   ├── pdf/                       # PDF 源文件（放置待索引的 PDF）
│   ├── pdf_image/                 # PDF 转图片（按文档名分文件夹）
│   │   └── {doc_name}/            # 文档图片文件夹
│   │       ├── page_1.jpg
│   │       ├── page_2.jpg
│   │       └── ...
│   ├── json_data/                 # 文档数据（按文档名分文件夹）
│   │   └── {doc_name}/            # 文档数据文件夹
│   │       ├── data.json          # 原始提取数据
│   │       ├── structure.json     # 文档结构（章节信息）
│   │       └── chunks.json        # 分块数据（用于向量化）
│   ├── vector_db/                 # 向量数据库（FAISS 索引）
│   │   └── {doc_name}/            # 文档向量数据库
│   ├── output/                    # 生成的摘要文件
│   │   └── {doc_name}/
│   │       ├── brief_summary.md   # 简要摘要
│   │       └── detailed_summary.pdf # 详细摘要（可选）
│   ├── sessions/                  # 会话数据
│   │   ├── single/                # 单文档模式会话（按 doc_name.json 命名）
│   │   ├── cross/                 # 跨文档智能模式会话（按 session_id.json 命名）
│   │   ├── manual/                # 跨文档手动模式会话（按 session_id.json 命名）
│   │   ├── backups/               # 会话备份（保留最近 10 个）
│   │   └── exports/               # 用户导出的会话
│   └── doc_registry.json          # 文档注册表（元数据、处理状态、文件路径）
├── tests/                         # 测试文件
│   ├── test_answer_agent.py
│   ├── test_retrieval_agent.py
│   ├── test_vector_db_content.py
│   └── ...
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

### 1. 支持哪些文件格式？
- ✅ **PDF 文件**：完全支持，自动提取文本、图片、结构
- ❌ **URL/网页**：暂时不支持（已移除 Web Reader 功能）
- ❌ **Word/PPT**：暂不支持（计划中）

### 2. 四种对话模式有什么区别？
- **Single（单文档）**：专注单个文档的深度问答，所有检索限定在选中文档内
- **Cross（跨文档智能）**：系统自动选择与问题最相关的文档进行检索和综合
- **Manual（跨文档手动）**：手动指定多个文档作为背景知识，系统在这些文档中检索
- **General（通用）**：不依赖任何文档的纯 LLM 对话

**推荐使用场景：**
- 学习特定文档内容 → Single 模式
- 探索性研究、不确定用哪个文档 → Cross 模式
- 明确需要对比多个文档 → Manual 模式
- 通用问题、闲聊 → General 模式

### 3. 如何索引新文档？
**CLI 模式：**
```bash
python main.py
# 选择 'i' - 索引新文档
# 从 data/pdf/ 目录选择文件
# 等待索引完成（自动解析、分块、向量化）
```

**Web 模式：**
```
访问 http://localhost:8000/
点击"批量索引"或"单个索引"
上传 PDF 文件
等待后台处理完成
```

### 4. 如何查看和管理已索引的文档？
**CLI 模式：**
```bash
python main.py
# 选择 'm' - 管理文档
# 查看文档列表和存储占用
# 可删除特定文档
```

**Web 模式：**
```
访问 http://localhost:8000/data
查看所有文档和数据类型
使用细粒度删除（只删除特定数据类型）
或批量删除多个文档
```

### 5. 什么是"细粒度删除"？
**传统删除**：删除文档时删除所有相关数据

**细粒度删除**：可选择性删除特定数据类型，例如：
- 只删除 Images（PDF 图片）→ 释放最多空间
- 只删除 Vector DB → 重建索引时使用
- 只删除 Summary → 重新生成摘要时使用
- 保留 JSON 数据 → 避免重新解析 PDF

**使用场景：**
- 空间不足但想保留文档 → 删除 Images
- 索引损坏需要重建 → 删除 Vector DB
- 优化索引参数 → 删除 Vector DB 和 Chunks，保留 JSON

### 6. 对话历史如何管理？
**自动管理：**
- LLM 自动总结历史对话（90%+ 压缩率）
- 保持上下文连贯性的同时节省 token

**手动清空：**
- **CLI**：输入 `clear` 命令
- **Web**：点击"清空历史"按钮
- 清空操作同时清除文件和内存，并重新实例化 Agent

**会话持久化：**
- 所有对话自动保存到 `data/sessions/{mode}/` 目录
- 三种模式独立存储：single、cross、manual
- Single 模式：每个文档一个会话文件（doc_name.json）
- Cross/Manual 模式：每个会话一个文件（session_id.json）


### 7. 如何切换 LLM 提供商？
**方法 1：修改 .env 文件**
```bash
# Azure OpenAI
CHAT_API_KEY=your_azure_key
CHAT_AZURE_ENDPOINT=https://your-endpoint.openai.azure.com/
CHAT_DEPLOYMENT_NAME=gpt-4
CHAT_API_VERSION=2024-02-15-preview

# OpenAI
CHAT_API_KEY=your_openai_key
CHAT_MODEL_NAME=gpt-4
OPENAI_BASE_URL=https://api.openai.com/v1/

# Ollama（本地）
OLLAMA_BASE_URL=http://localhost:11434
CHAT_MODEL_NAME=llama3

# Gemini
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL_NAME=gemini-1.5-pro
```

**方法 2：Web 配置页面**
```
访问 http://localhost:8000/config
选择 LLM 提供商
填写 API Key 和配置
保存并重启
```

### 8. 如何清理旧数据释放空间？
**智能清理（推荐）：**
```
访问 http://localhost:8000/data
点击"智能清理"
设置天数（默认 30 天）
系统自动清理旧数据
```

**手动清理：**
- 选择特定文档 → 细粒度删除（只删除 Images/Vector DB）
- 批量选择 → 一次删除多个文档
- 缓存管理 → 清空 PDF 图片缓存、JSON 缓存

**最占空间的数据类型：**
1. Images（PDF 图片）- 通常占 60-70% 空间
2. Vector DB（向量索引）- 通常占 20-30% 空间
3. JSON 数据 - 通常占 5-10% 空间
4. Summary - 通常占 1-2% 空间


### 9. 为什么移除了 Web Reader 功能？
- 专注于 PDF 文档的深度解析和问答
- Web 内容结构复杂，质量参差不齐
- 计划未来重新设计更好的 Web 内容处理方案

</details>

---

<details>
<summary><b>📝 更新日志 | Changelog（点击展开）</b></summary>

### 2026-01-29 - 批量索引和会话管理增强
- 🐛 **批量索引修复**
  - ✅ 修复批量 PDF 索引时的并发写入竞争条件
  - ✅ 增强 DocumentRegistry 并发安全性（重载-保存模式）
  - ✅ 确保多文档同时索引时所有文档都能正确注册
  - ✅ 新增 `update_metadata()` 方法支持安全的元数据更新
- 💬 **会话管理优化**
  - ✅ 修复清空聊天历史功能（同时清空文件和内存）
  - ✅ 清空历史时重新实例化 AnswerAgent 和 RetrievalAgent
  - ✅ 修复内存-文件同步问题（更新 `current_session` 防止返回过期数据）
  - ✅ 修复单文档模式会话详情加载（支持通过 session_id 查找文件）
- 🎨 **UI 增强**
  - ✅ 所有聊天模式添加时间戳显示（格式：年/月/日 时:分:秒）
  - ✅ 会话详情弹窗支持 Markdown 和 LaTeX 渲染
  - ✅ 历史消息加载时正确显示原始时间戳（而非当前时间）
- 🔧 **代码改进**
  - ✅ 统一 AnswerAgent 初始化参数（仅使用 `doc_name`）
  - ✅ 增强并发环境下的数据一致性保证

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
