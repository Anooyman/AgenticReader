# AgenticReader 架构重构计划

**版本**: v1.0
**创建日期**: 2026-01-14
**状态**: 待开始

---

## 📋 目录

1. [重构概述](#重构概述)
2. [目标架构](#目标架构)
3. [分阶段计划](#分阶段计划)
4. [详细文件映射](#详细文件映射)
5. [测试与验证](#测试与验证)
6. [风险与应对](#风险与应对)

---

## 🎯 重构概述

### 当前问题

1. **职责混杂**：
   - `readers/` 目录承担了太多职责：内容提取 + 摘要生成 + Vector DB构建 + 检索
   - `RetrivalAgent` 实际是agent，却放在readers目录

2. **层次不清**：
   - `core/vector_db/` 和实际使用场景脱节
   - `parsers/` 和 `core/processing/` 功能重复

3. **扩展性差**：
   - 单文档处理模式，多文档支持困难
   - 缺少统一的工具注册机制

### 重构目标

1. **清晰的Agent架构**：基于LangGraph的多Agent系统
2. **灵活的Tool系统**：任何Agent可配置任何Tool
3. **统一的处理层**：合并parsers和processing
4. **多文档支持**：统一索引管理，跨文档检索
5. **向后兼容**：保留现有chat/系统，渐进式迁移

---

## 🏗️ 目标架构

### 最终目录结构

```
src/
├── agents/                          # Agent层（新增）
│   ├── base.py                      # AgentBase基类
│   ├── answer/                      # Answer Agent
│   ├── retrieval/                   # Retrieval Agent
│   ├── indexing/                    # Indexing Agent
│   └── tools/                       # 工具层
│       ├── registry.py              # 工具注册中心
│       ├── vectordb/                # Vector DB工具集
│       ├── text/                    # 文本处理工具
│       └── document/                # 文档操作工具
│
├── processing/                      # 统一处理层（重构）
│   ├── pdf/                         # PDF处理
│   ├── web/                         # Web处理
│   ├── text/                        # 文本处理
│   └── embedding/                   # Embedding生成
│
├── core/
│   └── llm/                         # 只保留LLM抽象层
│
├── chat/                            # 保留现有系统
├── utils/                           # 保持不变
├── config/                          # 保持不变
└── ui/                              # 后续适配
```

### 核心设计原则

1. **Agent = 独立业务单元**：包含完整的业务逻辑
2. **Tool = 可复用功能**：通过Registry注册，任意组合
3. **Processing = 纯数据处理**：不包含业务逻辑
4. **Core = 底层基础设施**：只保留LLM抽象

---

## 📅 分阶段计划

### 总体时间线

```
Phase 0: 准备工作     [1天]
Phase 1: 基础设施     [2-3天]
Phase 2: Tool系统     [3-4天]
Phase 3: Agent实现    [4-5天]
Phase 4: 集成测试     [2-3天]
Phase 5: UI适配       [2-3天]
Phase 6: 清理优化     [1-2天]
```

---

## Phase 0: 准备工作

**目标**: 创建新目录结构，不影响现有代码

**预计时间**: 1天

### 步骤清单

- [ ] 创建新目录结构
  ```bash
  mkdir -p src/agents/{answer,retrieval,indexing,tools/{vectordb,text,document}}
  mkdir -p src/processing/{pdf,web,text,embedding}
  ```

- [ ] 创建测试环境
  ```bash
  # 备份当前代码
  git checkout -b feature/agent-refactoring

  # 创建测试目录
  mkdir -p tests/agents
  mkdir -p tests/processing
  ```

- [ ] 准备迁移工具
  - [ ] 创建 `scripts/check_imports.py` - 检查导入依赖
  - [ ] 创建 `scripts/migrate_files.py` - 批量文件迁移脚本

### 输出文件

```
docs/refactoring/
├── REFACTORING_PLAN.md          # 本文件
├── PHASE_0_CHECKLIST.md         # Phase 0检查清单
└── MIGRATION_LOG.md             # 迁移日志模板
```

### 验证标准

- ✅ 新目录结构已创建
- ✅ 现有代码运行正常
- ✅ Git分支已创建

---

## Phase 1: 基础设施层

**目标**: 实现Agent基类和Tool注册系统

**预计时间**: 2-3天

### 1.1 实现Tool Registry

**新建文件**:
- `src/agents/tools/__init__.py`
- `src/agents/tools/registry.py`

**功能要求**:
- 工具注册装饰器 `@ToolRegistry.register()`
- 工具发现 `ToolRegistry.list_tools()`
- 工具获取 `ToolRegistry.get(name)`
- OpenAI function calling schema生成

**代码示例**: 见附录A

**测试**:
```python
# tests/agents/test_tool_registry.py
def test_register_tool():
    @ToolRegistry.register("test_tool")
    async def test_func(param: str):
        """Test tool"""
        return param

    assert "test_tool" in ToolRegistry.list_tools()
    tool = ToolRegistry.get("test_tool")
    assert tool is not None
```

### 1.2 实现Agent基类

**新建文件**:
- `src/agents/__init__.py`
- `src/agents/base.py`

**功能要求**:
- 支持动态工具配置
- 工具执行方法 `execute_tool()`
- 工具描述生成 `get_tool_descriptions()`
- 抽象方法 `build_graph()`

**代码示例**: 见附录B

**测试**:
```python
# tests/agents/test_agent_base.py
def test_agent_tool_management():
    agent = TestAgent(tools=["tool1", "tool2"])
    assert "tool1" in agent.tools

    agent.add_tool("tool3", lambda: "test")
    assert "tool3" in agent.tools
```

### 1.3 整合Processing层

**迁移操作**:

```bash
# 移动text_splitter
src/core/processing/text_splitter.py → src/processing/text/splitter.py

# 创建新模块
touch src/processing/__init__.py
touch src/processing/text/__init__.py
```

**更新导入**:
```python
# 旧导入
from src.core.processing.text_splitter import StrictOverlapSplitter

# 新导入
from src.processing.text.splitter import StrictOverlapSplitter
```

**需要更新的文件**:
- `src/readers/base.py`
- `src/readers/parallel_processor.py`
- 所有引用text_splitter的测试文件

### 验证标准

- ✅ Tool Registry单元测试通过
- ✅ Agent Base单元测试通过
- ✅ Processing层迁移完成，现有测试通过
- ✅ 无破坏性变更

---

## Phase 2: Tool系统实现

**目标**: 实现所有Vector DB相关工具

**预计时间**: 3-4天

### 2.1 实现FAISS底层操作

**新建文件**:
- `src/agents/tools/vectordb/__init__.py`
- `src/agents/tools/vectordb/_faiss_ops.py`

**迁移内容**:
从 `src/core/vector_db/vector_db_client.py` 提取：
- `VectorDBClient` → `FAISSOperations`
- 移除LLMBase继承，改为依赖注入
- 添加全局实例管理 `get_faiss_instance()`

**关键改动**:
```python
# 旧代码
class VectorDBClient(LLMBase):
    def __init__(self, db_path: str, provider: str = 'openai'):
        super().__init__(provider)
        self.embedding_model = self.embedding_model  # 从父类获取

# 新代码
class FAISSOperations:
    def __init__(self, db_path: str, embedding_model=None):
        self.embedding_model = embedding_model  # 依赖注入
```

### 2.2 实现Vector DB工具

**新建文件**:
- `src/agents/tools/vectordb/build_index.py`
- `src/agents/tools/vectordb/search.py`
- `src/agents/tools/vectordb/manage.py`

**工具列表**:

| 工具名 | 文件 | 功能 |
|--------|------|------|
| `build_vector_index` | `build_index.py` | 构建向量索引 |
| `search_by_context` | `search.py` | 语义检索 |
| `search_by_title` | `search.py` | 标题检索 |
| `update_index` | `manage.py` | 更新索引 |
| `delete_index` | `manage.py` | 删除索引 |
| `list_indices` | `manage.py` | 列出所有索引 |

**代码框架**:
```python
# src/agents/tools/vectordb/build_index.py
from ..registry import ToolRegistry
from ._faiss_ops import get_faiss_instance

@ToolRegistry.register("build_vector_index")
async def build_vector_index(
    doc_name: str,
    chunks: List[Dict],
    metadata: Dict = None,
    db_path: str = None
) -> str:
    """构建文档的向量索引"""
    # 实现逻辑
    pass
```

### 2.3 实现文本处理工具

**新建文件**:
- `src/agents/tools/text/__init__.py`
- `src/agents/tools/text/summarize.py`
- `src/agents/tools/text/auto_tag.py`

**工具列表**:

| 工具名 | 功能 |
|--------|------|
| `summarize_brief` | 生成简要摘要 |
| `summarize_detail` | 生成详细摘要 |
| `auto_tag_document` | LLM自动标签 |

**实现要点**:
- 从 `src/readers/base.py` 提取摘要生成逻辑
- 独立为可复用的工具函数
- 保持原有的并行处理能力

### 2.4 实现文档操作工具

**新建文件**:
- `src/agents/tools/document/__init__.py`
- `src/agents/tools/document/get_structure.py`

**工具列表**:

| 工具名 | 功能 |
|--------|------|
| `get_document_structure` | 获取文档目录结构 |
| `extract_metadata` | 提取文档元数据 |

### 验证标准

- ✅ 所有工具注册成功
- ✅ FAISS操作独立测试通过
- ✅ 每个工具有单元测试
- ✅ `ToolRegistry.list_tools()` 返回所有工具

---

## Phase 3: Agent实现

**目标**: 实现三个核心Agent

**预计时间**: 4-5天

### 3.1 实现Indexing Agent

**新建文件**:
- `src/agents/indexing/__init__.py`
- `src/agents/indexing/agent.py`
- `src/agents/indexing/state.py`
- `src/agents/indexing/doc_registry.py`

**Workflow**:
```
parse → chunk → summarize → tag → build_index → register
```

**State定义**:
```python
class IndexingState(TypedDict):
    # 输入
    doc_name: str
    doc_path: str
    doc_type: Literal["pdf", "url"]
    manual_tags: Optional[List[str]]

    # 中间状态
    raw_data: Optional[str]
    chunks: Optional[List[Dict]]
    brief_summary: Optional[str]
    detailed_summaries: Optional[Dict]
    tags: Optional[List[str]]

    # 输出
    index_path: Optional[str]
    doc_id: Optional[str]
    status: str
```

**使用的工具**:
- `build_vector_index`
- `summarize_brief`
- `summarize_detail`
- `auto_tag_document`

**文档注册表**:
```python
# src/agents/indexing/doc_registry.py
class DocumentRegistry:
    """
    多文档注册管理

    存储结构：
    {
        "doc_id": {
            "doc_name": str,
            "doc_path": str,
            "index_path": str,
            "tags": List[str],
            "brief_summary": str,
            "created_at": str,
            "indexed_at": str,
            "metadata": Dict
        }
    }
    """
    def register(self, ...): pass
    def get(self, doc_id): pass
    def search_by_tags(self, tags): pass
    def list_all(self): pass
```

### 3.2 实现Retrieval Agent

**新建文件**:
- `src/agents/retrieval/__init__.py`
- `src/agents/retrieval/agent.py`
- `src/agents/retrieval/state.py`

**迁移来源**:
- 从 `src/readers/retrieval.py` 迁移
- 保留ReAct loop逻辑
- 增强多文档支持

**Workflow**:
```
think → act → observe → evaluate → (continue/finish)
```

**State定义**:
```python
class RetrievalState(TypedDict):
    # 输入
    query: str
    doc_name: Optional[str]  # None=多文档检索
    tags: Optional[List[str]]

    # ReAct loop
    thoughts: List[str]
    actions: List[Dict]
    observations: List[str]
    current_tool: Optional[str]
    current_params: Optional[Dict]
    last_result: Optional[Any]

    # 输出
    retrieved_content: Dict
    is_complete: bool
    max_iterations: int
```

**使用的工具**:
- `search_by_context`
- `search_by_title`
- `get_document_structure`

**多文档检索增强**:
```python
async def think(self, state: RetrievalState) -> Command:
    """思考：选择检索策略"""
    if state.doc_name is None:
        # 跨文档检索策略
        # 1. 先在所有文档的summary中检索
        # 2. 确定最相关的1-3个文档
        # 3. 在这些文档中深度检索
        pass
    else:
        # 单文档检索策略（原有逻辑）
        pass
```

### 3.3 实现Answer Agent

**新建文件**:
- `src/agents/answer/__init__.py`
- `src/agents/answer/agent.py`
- `src/agents/answer/state.py`

**Workflow**:
```
analyze_intent → (retrieve/direct) → generate_answer
```

**State定义**:
```python
class AnswerState(TypedDict):
    # 输入
    user_query: str
    current_doc: Optional[str]
    doc_tags: Optional[List[str]]
    conversation_history: Optional[List[Dict]]

    # 中间状态
    needs_retrieval: bool
    context: Optional[str]

    # 输出
    final_answer: str
    is_complete: bool
```

**Agent编排**:
```python
class AnswerAgent(AgentBase):
    def __init__(self):
        super().__init__(name="AnswerAgent")
        self.retrieval_agent = None  # 延迟加载

    async def call_retrieval(self, state):
        if not self.retrieval_agent:
            from ..retrieval import RetrievalAgent
            self.retrieval_agent = RetrievalAgent()

        result = await self.retrieval_agent.graph.ainvoke(...)
        return result
```

### 3.4 实现Workflow路由器

**新建文件**:
- `src/workflows.py`

**功能**:
```python
class WorkflowRouter:
    """工作流路由器：新旧架构共存"""

    async def route(
        self,
        query: str,
        mode: Literal["simple", "complex"] = "simple"
    ):
        if mode == "simple":
            return await self._run_answer_agent(query)
        else:
            return await self._run_plan_agent(query)
```

### 验证标准

- ✅ 每个Agent的graph构建成功
- ✅ 单Agent测试通过
- ✅ Agent间调用测试通过
- ✅ Workflow路由器测试通过

---

## Phase 4: 集成测试

**目标**: 端到端测试，确保新架构正常工作

**预计时间**: 2-3天

### 4.1 单元测试

**测试文件**:
```
tests/agents/
├── test_tool_registry.py         # Tool注册测试
├── test_agent_base.py            # Agent基类测试
├── test_indexing_agent.py        # Indexing Agent测试
├── test_retrieval_agent.py       # Retrieval Agent测试
└── test_answer_agent.py          # Answer Agent测试

tests/agents/tools/
├── test_vectordb_tools.py        # Vector DB工具测试
├── test_text_tools.py            # 文本工具测试
└── test_document_tools.py        # 文档工具测试
```

### 4.2 集成测试

**测试场景**:

**场景1: 单PDF索引和问答**
```python
async def test_single_pdf_workflow():
    # 1. 使用Indexing Agent构建索引
    indexing_agent = IndexingAgent()
    result = await indexing_agent.graph.ainvoke({
        "doc_name": "test.pdf",
        "doc_path": "data/pdf/test.pdf",
        "doc_type": "pdf"
    })
    assert result["status"] == "completed"

    # 2. 使用Answer Agent问答
    answer_agent = AnswerAgent()
    answer = await answer_agent.graph.ainvoke({
        "user_query": "这个文档讲了什么？",
        "current_doc": "test.pdf"
    })
    assert len(answer["final_answer"]) > 0
```

**场景2: 多PDF跨文档检索**
```python
async def test_multi_pdf_workflow():
    # 1. 索引多个文档
    docs = ["doc1.pdf", "doc2.pdf", "doc3.pdf"]
    for doc in docs:
        await indexing_agent.graph.ainvoke({
            "doc_name": doc,
            "doc_path": f"data/pdf/{doc}",
            "doc_type": "pdf"
        })

    # 2. 跨文档检索
    answer_agent = AnswerAgent()
    answer = await answer_agent.graph.ainvoke({
        "user_query": "这三个文档的共同主题是什么？",
        "current_doc": None  # None表示多文档
    })
    assert "doc1" in answer["final_answer"] or \
           "doc2" in answer["final_answer"] or \
           "doc3" in answer["final_answer"]
```

**场景3: 标签分组检索**
```python
async def test_tag_based_retrieval():
    # 1. 索引时添加标签
    await indexing_agent.graph.ainvoke({
        "doc_name": "ml_paper.pdf",
        "doc_path": "data/pdf/ml_paper.pdf",
        "doc_type": "pdf",
        "manual_tags": ["机器学习", "技术"]
    })

    # 2. 按标签检索
    answer = await answer_agent.graph.ainvoke({
        "user_query": "机器学习领域有哪些进展？",
        "doc_tags": ["机器学习"]
    })
    assert len(answer["final_answer"]) > 0
```

### 4.3 性能测试

**测试指标**:
- 索引构建时间（单文档）
- 检索响应时间（单文档 vs 多文档）
- 内存占用（FAISS索引大小）
- 并发处理能力

**测试脚本**:
```bash
# tests/performance/benchmark.py
python tests/performance/benchmark.py --docs 10 --queries 100
```

### 4.4 向后兼容测试

**测试旧代码路径**:
```python
def test_backward_compatibility():
    # 确保旧的readers/还能工作
    from src.readers.pdf import PDFReader

    reader = PDFReader()
    result = reader.main("test.pdf")

    assert result is not None
```

### 验证标准

- ✅ 所有单元测试通过（覆盖率 > 80%）
- ✅ 所有集成测试通过
- ✅ 性能基准达标
- ✅ 向后兼容性保持

---

## Phase 5: UI适配

**目标**: 更新UI层调用新架构

**预计时间**: 2-3天

### 5.1 更新API端点

**修改文件**:
- `src/ui/backend/api/v1/pdf.py`
- `src/ui/backend/api/v1/chat.py`
- `src/ui/backend/api/v1/web.py`

**改动示例**:

```python
# src/ui/backend/api/v1/pdf.py

# 旧代码
from src.readers.pdf import PDFReader

@router.post("/upload")
async def upload_pdf(file: UploadFile):
    reader = PDFReader()
    result = reader.main(file.filename)
    return result

# 新代码
from src.agents.indexing import IndexingAgent

@router.post("/upload")
async def upload_pdf(file: UploadFile):
    # 保存文件
    file_path = save_uploaded_file(file)

    # 使用Indexing Agent
    indexing_agent = IndexingAgent()
    result = await indexing_agent.graph.ainvoke({
        "doc_name": file.filename,
        "doc_path": file_path,
        "doc_type": "pdf"
    })

    return {
        "doc_id": result["doc_id"],
        "index_path": result["index_path"],
        "tags": result["tags"],
        "summary": result["brief_summary"]
    }
```

```python
# src/ui/backend/api/v1/chat.py

# 新增：工作流模式选择
@router.post("/chat")
async def chat(request: ChatRequest):
    from src.workflows import WorkflowRouter

    router = WorkflowRouter()

    # 简单问答使用Answer Agent
    # 复杂任务使用Plan Agent
    mode = "simple" if is_simple_query(request.query) else "complex"

    answer = await router.route(
        query=request.query,
        mode=mode,
        current_doc=request.doc_name
    )

    return {"answer": answer}
```

### 5.2 添加多文档管理API

**新建文件**:
- `src/ui/backend/api/v1/documents.py`

**端点列表**:

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/documents` | 列出所有文档 |
| GET | `/api/v1/documents/{doc_id}` | 获取文档详情 |
| POST | `/api/v1/documents/search` | 跨文档检索 |
| PATCH | `/api/v1/documents/{doc_id}/tags` | 更新文档标签 |
| DELETE | `/api/v1/documents/{doc_id}` | 删除文档 |

**实现示例**:
```python
# src/ui/backend/api/v1/documents.py

from fastapi import APIRouter
from src.agents.indexing.doc_registry import DocumentRegistry

router = APIRouter()
registry = DocumentRegistry()

@router.get("/")
async def list_documents(tags: List[str] = None):
    """列出所有文档"""
    if tags:
        docs = registry.search_by_tags(tags)
    else:
        docs = registry.list_all()

    return {"documents": docs, "count": len(docs)}

@router.post("/search")
async def search_documents(query: str, tags: List[str] = None):
    """跨文档检索"""
    from src.agents.answer import AnswerAgent

    agent = AnswerAgent()
    result = await agent.graph.ainvoke({
        "user_query": query,
        "current_doc": None,  # 多文档模式
        "doc_tags": tags
    })

    return {"answer": result["final_answer"]}
```

### 5.3 更新前端

**修改文件**:
- `src/ui/static/js/app.js` - 主应用逻辑
- `src/ui/templates/index.html` - 主页面

**新增功能**:
1. **多文档选择器**
   ```html
   <div class="document-selector">
       <label>
           <input type="checkbox" value="all"> 搜索所有文档
       </label>
       <div id="document-list">
           <!-- 动态加载文档列表 -->
       </div>
   </div>
   ```

2. **标签管理界面**
   ```html
   <div class="tag-manager">
       <h3>文档标签</h3>
       <div id="auto-tags">自动标签: <span class="tags"></span></div>
       <div id="manual-tags">
           <input type="text" placeholder="添加自定义标签">
           <button>添加</button>
       </div>
   </div>
   ```

3. **工作流模式切换**
   ```html
   <div class="workflow-mode">
       <label>
           <input type="radio" name="mode" value="simple" checked>
           简单问答（Answer Agent）
       </label>
       <label>
           <input type="radio" name="mode" value="complex">
           复杂任务（Plan Agent）
       </label>
   </div>
   ```

### 验证标准

- ✅ 所有API端点正常工作
- ✅ 前端功能正常
- ✅ WebSocket实时通信正常
- ✅ 多文档功能可用

---

## Phase 6: 清理与优化

**目标**: 移除旧代码，优化性能，完善文档

**预计时间**: 1-2天

### 6.1 代码清理

**标记废弃**:
```python
# src/readers/retrieval.py
import warnings

warnings.warn(
    "src.readers.retrieval is deprecated. "
    "Use src.agents.retrieval instead.",
    DeprecationWarning
)

# 保留旧接口一段时间，内部调用新实现
from src.agents.retrieval import RetrievalAgent as _NewRetrievalAgent

class RetrivalAgent(_NewRetrievalAgent):
    """Deprecated: Use src.agents.retrieval.RetrievalAgent instead"""
    pass
```

**移除文件清单**:
- [ ] `src/core/vector_db/vector_db_client.py` ✅ 已迁移到 `agents/tools/vectordb/_faiss_ops.py`
- [ ] `src/core/processing/text_splitter.py` ✅ 已迁移到 `processing/text/splitter.py`
- [ ] `src/readers/retrieval.py` ⚠️ 保留deprecation wrapper
- [ ] `src/config/tools/retrieval_tools.py` ✅ 已整合到 `agents/tools/`

**清理时间表**:
- Week 1-2: 添加deprecation警告
- Week 3-4: 监控使用情况
- Week 5+: 确认无引用后删除

### 6.2 性能优化

**优化点**:

1. **FAISS索引缓存**
   ```python
   # 全局实例池，避免重复加载
   _faiss_instance_pool = {}

   def get_faiss_instance(doc_name, db_path, embedding_model):
       cache_key = f"{doc_name}:{db_path}"
       if cache_key not in _faiss_instance_pool:
           _faiss_instance_pool[cache_key] = FAISSOperations(...)
       return _faiss_instance_pool[cache_key]
   ```

2. **并行索引构建**
   ```python
   # 多文档并行索引
   async def batch_index_documents(docs: List[str]):
       tasks = [
           indexing_agent.graph.ainvoke({"doc_name": doc, ...})
           for doc in docs
       ]
       results = await asyncio.gather(*tasks)
       return results
   ```

3. **检索结果缓存**
   ```python
   # LRU缓存常见查询
   from functools import lru_cache

   @lru_cache(maxsize=100)
   def cached_search(query_hash: str):
       # 缓存检索结果
       pass
   ```

### 6.3 文档完善

**创建文档**:

1. **用户文档**
   - `docs/USER_GUIDE.md` - 用户使用指南
   - `docs/MULTI_DOC_GUIDE.md` - 多文档功能指南
   - `docs/API_REFERENCE.md` - API文档

2. **开发者文档**
   - `docs/ARCHITECTURE.md` - 架构说明
   - `docs/AGENT_DEVELOPMENT.md` - Agent开发指南
   - `docs/TOOL_DEVELOPMENT.md` - Tool开发指南

3. **更新CLAUDE.md**
   ```markdown
   # 新增章节

   ## Agent System Architecture

   AgenticReader使用基于LangGraph的多Agent系统：

   - **Answer Agent**: 用户对话接口
   - **Retrieval Agent**: 智能检索
   - **Indexing Agent**: 文档索引构建

   ### 添加新Agent

   1. 继承AgentBase
   2. 实现build_graph()
   3. 注册所需tools
   4. 定义State类型

   ### 添加新Tool

   1. 使用@ToolRegistry.register()装饰器
   2. 添加完整的docstring
   3. 实现async函数
   4. 编写单元测试
   ```

### 6.4 迁移检查清单

**逐项确认**:

- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 性能测试达标
- [ ] UI功能正常
- [ ] API文档完整
- [ ] 用户文档完整
- [ ] CLAUDE.md已更新
- [ ] CHANGELOG已更新
- [ ] 旧代码已标记deprecation
- [ ] Git commit历史清晰

### 验证标准

- ✅ 代码质量扫描通过（pylint, mypy）
- ✅ 测试覆盖率 > 85%
- ✅ 文档完整性检查通过
- ✅ 性能基准达标

---

## 📊 详细文件映射

### Vector DB相关

| 旧文件 | 新文件 | 操作 | 说明 |
|--------|--------|------|------|
| `src/core/vector_db/vector_db_client.py` | `src/agents/tools/vectordb/_faiss_ops.py` | 重构 | 移除LLMBase继承，改为依赖注入 |
| - | `src/agents/tools/vectordb/build_index.py` | 新建 | 构建索引工具 |
| - | `src/agents/tools/vectordb/search.py` | 新建 | 检索工具 |
| - | `src/agents/tools/vectordb/manage.py` | 新建 | 索引管理工具 |

### Processing相关

| 旧文件 | 新文件 | 操作 | 说明 |
|--------|--------|------|------|
| `src/core/processing/text_splitter.py` | `src/processing/text/splitter.py` | 移动 | 整合到processing层 |
| `src/readers/pdf.py` | `src/processing/pdf/extractor.py` | 拆分 | 只保留提取逻辑 |
| `src/readers/web.py` | `src/processing/web/extractor.py` | 拆分 | 只保留提取逻辑 |
| `src/readers/parallel_processor.py` | `src/utils/parallel/processor.py` | 移动 | 作为通用工具 |

### Retrieval相关

| 旧文件 | 新文件 | 操作 | 说明 |
|--------|--------|------|------|
| `src/readers/retrieval.py` | `src/agents/retrieval/agent.py` | 迁移 | 改为Agent实现 |
| `src/config/tools/retrieval_tools.py` | `src/agents/tools/document/` | 拆分 | 拆分为独立工具 |

### Reader Base相关

| 旧文件 | 新功能分布 | 操作 | 说明 |
|--------|-----------|------|------|
| `src/readers/base.py` (摘要生成) | `src/agents/tools/text/summarize.py` | 提取 | 作为独立工具 |
| `src/readers/base.py` (Vector DB构建) | `src/agents/tools/vectordb/build_index.py` | 提取 | 作为独立工具 |
| `src/readers/base.py` (内容提取) | `src/processing/pdf/extractor.py` | 移动 | 归入processing层 |

### 新增文件

| 文件 | 用途 |
|------|------|
| `src/agents/base.py` | Agent基类 |
| `src/agents/tools/registry.py` | 工具注册中心 |
| `src/agents/answer/agent.py` | Answer Agent |
| `src/agents/retrieval/agent.py` | Retrieval Agent |
| `src/agents/indexing/agent.py` | Indexing Agent |
| `src/agents/indexing/doc_registry.py` | 文档注册表 |
| `src/workflows.py` | 工作流路由器 |
| `src/ui/backend/api/v1/documents.py` | 多文档管理API |

---

## 🧪 测试与验证

### 测试策略

**测试金字塔**:
```
       /\
      /  \  E2E Tests (10%)
     /    \
    /------\  Integration Tests (30%)
   /        \
  /----------\  Unit Tests (60%)
 /____________\
```

### 单元测试覆盖

**必须覆盖**:
- [ ] Tool Registry (100%)
- [ ] Agent Base (100%)
- [ ] FAISS Operations (90%)
- [ ] 每个Tool (90%)
- [ ] 每个Agent (80%)

### 集成测试场景

1. **单文档工作流**
   - PDF上传 → 索引构建 → 检索问答
   - URL提交 → 索引构建 → 检索问答

2. **多文档工作流**
   - 批量索引 → 跨文档检索 → 结果聚合

3. **标签管理**
   - 自动标签生成 → 手动修改 → 按标签检索

4. **向后兼容**
   - 旧API调用 → 新实现响应
   - 旧数据格式 → 新系统处理

### 性能基准

| 指标 | 目标 | 测量方法 |
|------|------|----------|
| 单文档索引时间 | < 30s (10页PDF) | `time build_index()` |
| 单文档检索时间 | < 2s | `time search_by_context()` |
| 多文档检索时间 | < 5s (10个文档) | `time search_multi_docs()` |
| 内存占用 | < 500MB (10个文档) | `memory_profiler` |
| 并发处理 | > 10 req/s | `locust` |

### 回归测试

**确保不破坏**:
- [ ] 现有PDF处理功能
- [ ] 现有Web处理功能
- [ ] 现有Chat功能
- [ ] 现有UI功能
- [ ] 现有数据格式

---

## ⚠️ 风险与应对

### 风险1: 性能下降

**风险**: Agent调用链路变长，可能影响性能

**应对**:
- 实施性能监控
- 优化Agent调用路径
- 添加缓存机制
- 并行处理优化

**回滚方案**: 保留旧代码路径，通过配置切换

### 风险2: 数据迁移问题

**风险**: 旧格式Vector DB不兼容新系统

**应对**:
- 提供数据迁移脚本
- 支持新旧格式共存
- 自动检测格式并转换

**回滚方案**: 备份所有数据，支持格式回退

### 风险3: 依赖冲突

**风险**: LangGraph版本要求可能冲突

**应对**:
- 锁定依赖版本 (`requirements.lock`)
- 使用虚拟环境隔离
- 渐进式升级依赖

**回滚方案**: 保留旧的requirements.txt

### 风险4: 测试覆盖不足

**风险**: 边缘情况未测试导致生产问题

**应对**:
- 强制测试覆盖率 > 85%
- Code review重点检查测试
- 增加E2E测试

**回滚方案**: Git revert到稳定版本

### 风险5: 用户适应成本

**风险**: 新架构改变使用方式，用户不适应

**应对**:
- 保持API向后兼容
- 提供迁移指南
- 分阶段发布（alpha → beta → stable）

**回滚方案**: 保留旧API端点

---

## 📈 进度跟踪

### 检查清单

#### Phase 0: 准备工作
- [ ] 创建新目录结构
- [ ] 创建Git分支
- [ ] 准备迁移脚本
- [ ] 创建迁移日志

#### Phase 1: 基础设施
- [ ] Tool Registry实现
- [ ] Agent Base实现
- [ ] Processing层整合
- [ ] 单元测试通过

#### Phase 2: Tool系统
- [ ] FAISS Operations实现
- [ ] Vector DB工具实现
- [ ] 文本工具实现
- [ ] 文档工具实现
- [ ] 所有工具注册成功

#### Phase 3: Agent实现
- [ ] Indexing Agent实现
- [ ] Retrieval Agent实现
- [ ] Answer Agent实现
- [ ] Workflow路由器实现
- [ ] Agent测试通过

#### Phase 4: 集成测试
- [ ] 单元测试通过
- [ ] 集成测试通过
- [ ] 性能测试通过
- [ ] 向后兼容测试通过

#### Phase 5: UI适配
- [ ] API端点更新
- [ ] 多文档管理API
- [ ] 前端功能实现
- [ ] UI测试通过

#### Phase 6: 清理优化
- [ ] 代码清理
- [ ] 性能优化
- [ ] 文档完善
- [ ] 最终验证

### 里程碑

| 里程碑 | 预计日期 | 完成标准 |
|--------|----------|----------|
| M1: 基础设施完成 | Day 3 | Tool Registry + Agent Base可用 |
| M2: Tool系统完成 | Day 7 | 所有工具可用 |
| M3: Agent完成 | Day 12 | 三个Agent可用 |
| M4: 集成测试通过 | Day 15 | 所有测试通过 |
| M5: UI适配完成 | Day 18 | UI功能正常 |
| M6: 发布准备 | Day 20 | 文档完整，代码清理 |

---

## 📚 附录

### 附录A: Tool Registry实现

```python
# src/agents/tools/registry.py

from typing import Callable, Dict, Any
import inspect

class ToolRegistry:
    """全局工具注册中心"""

    _tools: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register(cls, name: str = None):
        """工具注册装饰器"""
        def decorator(func: Callable):
            tool_name = name or func.__name__

            sig = inspect.signature(func)
            doc = func.__doc__ or "No description"

            cls._tools[tool_name] = {
                "func": func,
                "signature": sig,
                "description": doc.strip(),
                "is_async": inspect.iscoroutinefunction(func)
            }

            return func

        return decorator

    @classmethod
    def get(cls, name: str) -> Callable:
        """获取工具函数"""
        tool = cls._tools.get(name)
        return tool["func"] if tool else None

    @classmethod
    def list_tools(cls) -> Dict[str, str]:
        """列出所有工具"""
        return {
            name: tool["description"]
            for name, tool in cls._tools.items()
        }

    @classmethod
    def get_tool_schema(cls, name: str) -> Dict:
        """获取工具的OpenAI function schema"""
        if name not in cls._tools:
            return None

        tool = cls._tools[name]
        sig = tool["signature"]

        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            param_type = param.annotation
            properties[param_name] = {
                "type": cls._python_type_to_json(param_type),
                "description": f"Parameter {param_name}"
            }

            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        return {
            "name": name,
            "description": tool["description"],
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }

    @staticmethod
    def _python_type_to_json(py_type) -> str:
        """Python类型转JSON schema类型"""
        mapping = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object"
        }
        return mapping.get(py_type, "string")
```

### 附录B: Agent Base实现

```python
# src/agents/base.py

from langgraph.graph import StateGraph
from typing import List, Dict, Callable, Any
from .tools.registry import ToolRegistry

class AgentBase:
    """Agent基类，支持动态工具配置"""

    def __init__(
        self,
        name: str,
        tools: List[str] = None,
        custom_tools: Dict[str, Callable] = None
    ):
        self.name = name
        self.tools = {}

        # 加载指定的内置工具
        if tools:
            for tool_name in tools:
                tool = ToolRegistry.get(tool_name)
                if tool:
                    self.tools[tool_name] = tool

        # 注册自定义工具
        if custom_tools:
            self.tools.update(custom_tools)

        self.graph = None

    def add_tool(self, name: str, func: Callable):
        """动态添加工具"""
        self.tools[name] = func

    def remove_tool(self, name: str):
        """移除工具"""
        self.tools.pop(name, None)

    def build_graph(self) -> StateGraph:
        """子类实现：构建LangGraph workflow"""
        raise NotImplementedError

    async def execute_tool(self, tool_name: str, **kwargs) -> Any:
        """执行工具调用"""
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not found")

        tool_func = self.tools[tool_name]
        return await tool_func(**kwargs)

    def get_tool_descriptions(self) -> str:
        """获取所有工具的描述（供LLM使用）"""
        descriptions = []
        for name, func in self.tools.items():
            desc = getattr(func, '__doc__', 'No description')
            descriptions.append(f"- {name}: {desc}")
        return "\n".join(descriptions)
```

### 附录C: 迁移脚本示例

```python
# scripts/migrate_files.py

import shutil
from pathlib import Path

MIGRATIONS = [
    # (source, destination)
    ("src/core/processing/text_splitter.py", "src/processing/text/splitter.py"),
    ("src/readers/retrieval.py", "src/agents/retrieval/agent.py"),
]

def migrate_files():
    for src, dst in MIGRATIONS:
        src_path = Path(src)
        dst_path = Path(dst)

        if not src_path.exists():
            print(f"⚠️  Source not found: {src}")
            continue

        # 创建目标目录
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        # 复制文件
        shutil.copy2(src_path, dst_path)
        print(f"✅ Migrated: {src} → {dst}")

if __name__ == "__main__":
    migrate_files()
```

### 附录D: 导入更新脚本

```python
# scripts/update_imports.py

import re
from pathlib import Path

IMPORT_REPLACEMENTS = {
    r"from src\.core\.processing\.text_splitter import":
        "from src.processing.text.splitter import",

    r"from src\.core\.vector_db\.vector_db_client import VectorDBClient":
        "from src.agents.tools.vectordb._faiss_ops import get_faiss_instance",

    r"from src\.readers\.retrieval import RetrivalAgent":
        "from src.agents.retrieval import RetrievalAgent",
}

def update_imports_in_file(file_path: Path):
    content = file_path.read_text()
    original_content = content

    for old_pattern, new_import in IMPORT_REPLACEMENTS.items():
        content = re.sub(old_pattern, new_import, content)

    if content != original_content:
        file_path.write_text(content)
        print(f"✅ Updated imports in: {file_path}")
        return True

    return False

def update_all_imports():
    python_files = Path("src").rglob("*.py")
    updated_count = 0

    for file_path in python_files:
        if update_imports_in_file(file_path):
            updated_count += 1

    print(f"\n✅ Updated {updated_count} files")

if __name__ == "__main__":
    update_all_imports()
```

---

## 📞 联系与反馈

**项目负责人**: [Your Name]
**开始日期**: 2026-01-14
**预计完成**: 2026-02-03

**状态更新频率**: 每2天更新一次进度

**反馈渠道**:
- GitHub Issues: 报告问题
- 每周例会: 讨论进展和阻塞

---

**版本历史**:
- v1.0 (2026-01-14): 初始版本
