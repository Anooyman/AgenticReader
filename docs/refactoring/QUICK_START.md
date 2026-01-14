# 重构快速开始指南

本文档提供重构工作的快速启动步骤。

**当前分支**: Feture1（直接在此分支上进行重构）

---

## 🚀 立即开始

### 1. 确认当前环境

```bash
cd /Users/edward_ke/Library/CloudStorage/OneDrive-Personal/AgenticReader

# 确认当前分支
git branch
# 应该显示 * Feture1

# 查看当前状态
git status

# 创建安全备份点（可选）
git tag backup-before-refactoring-$(date +%Y%m%d)
```

### 2. 创建基础目录结构

```bash
# Phase 0: 创建所有需要的目录
mkdir -p src/agents/{answer,retrieval,indexing,tools/{vectordb,text,document}}
mkdir -p src/processing/{pdf,web,text,embedding}
mkdir -p tests/agents/{answer,retrieval,indexing,tools}
mkdir -p tests/processing
mkdir -p docs/refactoring/logs

# 创建 __init__.py 文件
touch src/agents/__init__.py
touch src/agents/answer/__init__.py
touch src/agents/retrieval/__init__.py
touch src/agents/indexing/__init__.py
touch src/agents/tools/__init__.py
touch src/agents/tools/vectordb/__init__.py
touch src/agents/tools/text/__init__.py
touch src/agents/tools/document/__init__.py
touch src/processing/__init__.py
touch src/processing/pdf/__init__.py
touch src/processing/web/__init__.py
touch src/processing/text/__init__.py
touch src/processing/embedding/__init__.py

echo "✅ 目录结构创建完成"
```

### 3. 运行基线测试

在开始重构前，确保所有现有测试通过：

```bash
# 运行所有测试
python -m pytest tests/ -v

# 如果有测试失败，先修复再开始重构
# 记录基线测试结果
python -m pytest tests/ --cov=src --cov-report=html
mkdir -p docs/refactoring/baseline
cp -r htmlcov docs/refactoring/baseline/coverage_$(date +%Y%m%d)

echo "✅ 基线测试完成"
```

### 4. 创建迁移日志

```bash
# 创建日志文件
cat > docs/refactoring/logs/migration_log_$(date +%Y%m%d).md << EOF
# Migration Log - $(date +%Y-%m-%d)

## Changes Made

### Phase 0: Preparation
- [ ] Created directory structure
- [ ] Ran baseline tests
- [ ] Created migration log

### Phase 1: Infrastructure
- [ ] Implemented Tool Registry
- [ ] Implemented Agent Base
- [ ] Migrated Processing layer

### Notes
-

### Issues Encountered
-

EOF

echo "✅ 迁移日志已创建"
```

---

## 📋 分阶段执行

### Phase 0: 准备工作 (已完成上述步骤)

**时间**: 1小时

**提交节点**:
```bash
git add docs/refactoring/
git commit -m "docs: add refactoring plan and setup directories"
```

---

### Phase 1: 基础设施层

**时间**: 2-3天

**执行顺序**:

#### 步骤1: 实现Tool Registry (Day 1, 上午)

```bash
# 创建文件
cat > src/agents/tools/registry.py << 'EOF'
"""全局工具注册中心"""
from typing import Callable, Dict, Any
import inspect

class ToolRegistry:
    """工具注册表，支持装饰器注册和动态查询"""

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
EOF

# 创建测试
cat > tests/agents/test_tool_registry.py << 'EOF'
import pytest
from src.agents.tools.registry import ToolRegistry

def test_register_tool():
    @ToolRegistry.register("test_tool")
    async def test_func(param: str):
        """Test tool description"""
        return param

    assert "test_tool" in ToolRegistry.list_tools()
    tool = ToolRegistry.get("test_tool")
    assert tool is not None

def test_list_tools():
    tools = ToolRegistry.list_tools()
    assert isinstance(tools, dict)
EOF

# 运行测试
python -m pytest tests/agents/test_tool_registry.py -v

# 提交
git add src/agents/tools/registry.py tests/agents/test_tool_registry.py
git commit -m "feat: implement Tool Registry"
```

#### 步骤2: 实现Agent Base (Day 1, 下午)

```bash
# 创建文件
cat > src/agents/base.py << 'EOF'
"""Agent基类"""
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

        # 加载内置工具
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
        """子类实现：构建workflow"""
        raise NotImplementedError

    async def execute_tool(self, tool_name: str, **kwargs) -> Any:
        """执行工具调用"""
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not found")

        tool_func = self.tools[tool_name]
        return await tool_func(**kwargs)

    def get_tool_descriptions(self) -> str:
        """获取工具描述（供LLM使用）"""
        descriptions = []
        for name, func in self.tools.items():
            desc = getattr(func, '__doc__', 'No description')
            descriptions.append(f"- {name}: {desc}")
        return "\n".join(descriptions)
EOF

# 创建测试
cat > tests/agents/test_agent_base.py << 'EOF'
import pytest
from src.agents.base import AgentBase

class TestAgent(AgentBase):
    def build_graph(self):
        return None

def test_agent_tool_management():
    agent = TestAgent(name="test")

    # 添加工具
    agent.add_tool("tool1", lambda: "result")
    assert "tool1" in agent.tools

    # 移除工具
    agent.remove_tool("tool1")
    assert "tool1" not in agent.tools
EOF

# 运行测试
python -m pytest tests/agents/test_agent_base.py -v

# 提交
git add src/agents/base.py tests/agents/test_agent_base.py
git commit -m "feat: implement Agent Base class"
```

#### 步骤3: 迁移Processing层 (Day 2)

```bash
# 移动text_splitter
cp src/core/processing/text_splitter.py src/processing/text/splitter.py

# 更新processing/__init__.py
cat > src/processing/__init__.py << 'EOF'
"""
统一处理层

包含：
- PDF处理：pdf/extractor.py
- Web处理：web/extractor.py
- 文本处理：text/splitter.py
- Embedding：embedding/generator.py
"""
from .text.splitter import StrictOverlapSplitter

__all__ = ['StrictOverlapSplitter']
EOF

# 创建更新导入的脚本
cat > scripts/update_imports.py << 'EOF'
#!/usr/bin/env python3
import re
from pathlib import Path

# 需要更新的导入映射
REPLACEMENTS = {
    r"from src\.core\.processing\.text_splitter import":
        "from src.processing.text.splitter import",
}

def update_file(file_path: Path):
    content = file_path.read_text()
    original = content

    for old, new in REPLACEMENTS.items():
        content = re.sub(old, new, content)

    if content != original:
        file_path.write_text(content)
        print(f"✅ Updated: {file_path}")
        return True
    return False

def main():
    updated = 0
    for py_file in Path("src").rglob("*.py"):
        if update_file(py_file):
            updated += 1

    print(f"\n✅ Updated {updated} files")

if __name__ == "__main__":
    main()
EOF

chmod +x scripts/update_imports.py

# 运行导入更新
python scripts/update_imports.py

# 运行测试确保没破坏
python -m pytest tests/ -v

# 提交
git add src/processing/ scripts/update_imports.py
git commit -m "refactor: move text_splitter to processing layer"
```

**Phase 1完成检查**:
```bash
# 确认测试通过
python -m pytest tests/agents/ -v

# 提交阶段性成果
git add .
git commit -m "chore: complete Phase 1 - Infrastructure layer"
```

---

### Phase 2: Tool系统实现

**时间**: 3-4天

#### 步骤1: 实现FAISS Operations (Day 3)

```bash
# 创建_faiss_ops.py（从vector_db_client.py迁移）
# 关键改动：
# 1. VectorDBClient → FAISSOperations
# 2. 移除继承LLMBase
# 3. 改为依赖注入embedding_model

cat > src/agents/tools/vectordb/_faiss_ops.py << 'EOF'
"""
FAISS底层操作封装（私有模块）
⚠️ 仅供tools内部使用，不要直接导入
"""
import os
import hashlib
import logging
from typing import List, Dict, Optional, Set, Callable, Any
from langchain.docstore.document import Document
from langchain_community.vectorstores import FAISS

logger = logging.getLogger(__name__)

class FAISSOperations:
    """FAISS操作封装类（通过依赖注入获取embedding_model）"""

    def __init__(self, db_path: str, embedding_model=None):
        self.db_path = db_path
        self.embedding_model = embedding_model
        self.vector_db: Optional[FAISS] = None
        self._retrieved_doc_hashes: Set[str] = set()

        # 自动加载已存在的数据库
        if os.path.exists(db_path):
            try:
                self.load_vector_db()
                logger.info(f"✅ 成功加载向量数据库: {db_path}")
            except Exception as e:
                logger.warning(f"⚠️ 加载向量数据库失败: {e}")

    # ... 复制原VectorDBClient的方法，但不继承LLMBase
    # （完整代码见REFACTORING_PLAN.md附录）

# 全局实例管理
_global_faiss_instances: Dict[str, FAISSOperations] = {}

def get_faiss_instance(
    doc_name: str = "default",
    db_path: str = None,
    embedding_model = None
) -> FAISSOperations:
    """获取FAISS实例（单例模式）"""
    if doc_name not in _global_faiss_instances:
        if not db_path or not embedding_model:
            raise ValueError("首次创建需提供db_path和embedding_model")

        _global_faiss_instances[doc_name] = FAISSOperations(
            db_path=db_path,
            embedding_model=embedding_model
        )

    return _global_faiss_instances[doc_name]
EOF

# 从原文件复制完整实现
# 编辑 src/agents/tools/vectordb/_faiss_ops.py
# 复制 src/core/vector_db/vector_db_client.py 的所有方法

# 创建测试
cat > tests/agents/tools/test_faiss_ops.py << 'EOF'
import pytest
from src.agents.tools.vectordb._faiss_ops import FAISSOperations, get_faiss_instance

def test_faiss_operations():
    # 测试基本功能
    pass
EOF

# 提交
git add src/agents/tools/vectordb/_faiss_ops.py
git commit -m "refactor: implement FAISS operations (private module)"
```

#### 步骤2: 实现Vector DB工具 (Day 4)

```bash
# 创建build_index.py
cat > src/agents/tools/vectordb/build_index.py << 'EOF'
from typing import List, Dict
from langchain.docstore.document import Document
from ..registry import ToolRegistry
from ._faiss_ops import get_faiss_instance

@ToolRegistry.register("build_vector_index")
async def build_vector_index(
    doc_name: str,
    chunks: List[Dict],
    metadata: Dict = None,
    db_path: str = None
) -> str:
    """
    构建文档的向量索引

    Args:
        doc_name: 文档名称
        chunks: 文本分块列表
        metadata: 文档元数据
        db_path: 索引存储路径

    Returns:
        索引路径
    """
    from src.core.llm import LLMBase
    from pathlib import Path
    from src.config.settings import DATA_PATH

    # 获取embedding模型
    llm = LLMBase()
    embedding_model = llm.embedding_model

    # 构建存储路径
    if not db_path:
        db_path = DATA_PATH / "vector_db" / doc_name

    # 转换为Document对象
    documents = []
    base_metadata = metadata or {}

    for chunk in chunks:
        doc_metadata = {
            **base_metadata,
            "doc_name": doc_name,
            "page": chunk.get("page", "1"),
            "refactor": chunk["data"]
        }

        documents.append(
            Document(
                page_content=chunk["data"],
                metadata=doc_metadata
            )
        )

    # 构建索引
    faiss_ops = get_faiss_instance(
        doc_name=doc_name,
        db_path=str(db_path),
        embedding_model=embedding_model
    )

    faiss_ops.build_vector_db(documents)

    return str(db_path)
EOF

# 创建search.py
cat > src/agents/tools/vectordb/search.py << 'EOF'
from typing import List, Dict, Optional
from ..registry import ToolRegistry
from ._faiss_ops import get_faiss_instance

@ToolRegistry.register("search_by_context")
async def search_by_context(
    query: str,
    doc_name: str = None,
    tags: List[str] = None,
    top_k: int = 5,
    enable_dedup: bool = True
) -> Dict:
    """
    语义相似检索

    Args:
        query: 检索查询
        doc_name: 指定文档名（None=搜索所有）
        tags: 标签过滤
        top_k: 返回结果数

    Returns:
        检索结果字典
    """
    from src.core.llm import LLMBase

    # 构建metadata过滤
    metadata_filters = {}
    if doc_name:
        metadata_filters["doc_name"] = doc_name
    if tags:
        metadata_filters["tags"] = tags

    # 执行检索
    llm = LLMBase()
    faiss_ops = get_faiss_instance(
        doc_name=doc_name or "default",
        embedding_model=llm.embedding_model
    )

    results = faiss_ops.search_with_filter(
        query=query,
        k=top_k,
        metadata_filters=metadata_filters if metadata_filters else None,
        enable_dedup=enable_dedup
    )

    # 格式化结果
    formatted_results = []
    for doc, score in results:
        formatted_results.append({
            "content": doc.page_content,
            "metadata": doc.metadata,
            "score": float(score)
        })

    return {
        "query": query,
        "results": formatted_results,
        "count": len(formatted_results)
    }

@ToolRegistry.register("search_by_title")
async def search_by_title(
    title: str,
    doc_name: str = None,
    top_k: int = 1
) -> Dict:
    """按标题检索"""
    # 实现逻辑...
    pass
EOF

# 提交
git add src/agents/tools/vectordb/
git commit -m "feat: implement vector DB tools"
```

**其余步骤类似，按照REFACTORING_PLAN.md执行...**

---

## 🎯 每日工作流

### 开始工作
```bash
# 拉取最新代码（如果团队协作）
git pull origin Feture1

# 查看今天的任务
cat docs/refactoring/REFACTORING_PLAN.md | grep "Day X"

# 创建今日工作分支（可选，便于回滚）
git checkout -b daily/day-$(date +%Y%m%d)
```

### 结束工作
```bash
# 运行测试
python -m pytest tests/ -v

# 提交代码
git add .
git commit -m "feat/fix/refactor: [描述今日完成的内容]"

# 合并回Feture1（如果使用了daily分支）
git checkout Feture1
git merge daily/day-$(date +%Y%m%d)

# 推送（如果需要）
git push origin Feture1

# 更新迁移日志
# 编辑 docs/refactoring/logs/migration_log_*.md
```

---

## 📊 进度跟踪

```bash
# 查看当前进度
cat docs/refactoring/REFACTORING_PLAN.md | grep -A 5 "Phase X"

# 查看已完成的提交
git log --oneline --since="7 days ago"

# 查看测试覆盖率
python -m pytest tests/ --cov=src --cov-report=term
```

---

## 🆘 遇到问题？

### 快速回滚

```bash
# 查看最近的提交
git log --oneline -10

# 回滚到某个提交
git reset --hard <commit-hash>

# 或使用之前创建的备份标签
git reset --hard backup-before-refactoring-20260114
```

### 临时保存进度

```bash
# 临时保存当前更改（不提交）
git stash save "临时保存：描述"

# 查看stash列表
git stash list

# 恢复stash
git stash pop
```

---

**开始重构！** 🚀

所有详细步骤参考：`docs/refactoring/REFACTORING_PLAN.md`
