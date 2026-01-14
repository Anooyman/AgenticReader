"""
Agent Base 单元测试
"""

import pytest
from src.agents.base import AgentBase
from src.agents.tools.registry import ToolRegistry
from langgraph.graph import StateGraph
from typing import TypedDict


# 测试用的State定义
class TestState(TypedDict):
    value: str


# 测试用的Agent实现
class TestAgent(AgentBase):
    """简单的测试Agent"""

    def build_graph(self) -> StateGraph:
        """返回一个简单的graph"""
        workflow = StateGraph(TestState)
        # 这里只是测试，不需要完整的workflow
        return workflow


class TestAgentBase:
    """Agent Base测试类"""

    def setup_method(self):
        """每个测试前清空registry"""
        ToolRegistry.clear()

    def test_agent_initialization(self):
        """测试Agent基本初始化"""
        agent = TestAgent(name="test")

        assert agent.name == "test"
        assert len(agent.tools) == 0
        assert agent.graph is None

    def test_agent_with_registry_tools(self):
        """测试从Registry加载工具"""
        # 注册测试工具
        @ToolRegistry.register("tool1")
        def t1():
            """Tool 1"""
            return "result1"

        @ToolRegistry.register("tool2")
        def t2():
            """Tool 2"""
            return "result2"

        # 创建Agent并加载工具
        agent = TestAgent(name="test", tools=["tool1", "tool2"])

        assert agent.has_tool("tool1")
        assert agent.has_tool("tool2")
        assert len(agent.tools) == 2
        assert agent.list_tools() == ["tool1", "tool2"]

    def test_agent_with_custom_tools(self):
        """测试使用自定义工具"""
        def custom1():
            return "custom1"

        def custom2():
            return "custom2"

        agent = TestAgent(
            name="test",
            custom_tools={
                "custom1": custom1,
                "custom2": custom2
            }
        )

        assert agent.has_tool("custom1")
        assert agent.has_tool("custom2")
        assert len(agent.tools) == 2

    def test_agent_with_mixed_tools(self):
        """测试混合使用Registry和自定义工具"""
        # 注册工具
        @ToolRegistry.register("registry_tool")
        def rt():
            """Registry tool"""
            return "registry"

        # 自定义工具
        def custom_tool():
            return "custom"

        agent = TestAgent(
            name="test",
            tools=["registry_tool"],
            custom_tools={"custom_tool": custom_tool}
        )

        assert agent.has_tool("registry_tool")
        assert agent.has_tool("custom_tool")
        assert len(agent.tools) == 2

    def test_add_tool(self):
        """测试动态添加工具"""
        agent = TestAgent(name="test")

        def new_tool():
            return "new"

        agent.add_tool("new_tool", new_tool)

        assert agent.has_tool("new_tool")
        assert len(agent.tools) == 1

    def test_remove_tool(self):
        """测试移除工具"""
        def tool1():
            return "t1"

        agent = TestAgent(
            name="test",
            custom_tools={"tool1": tool1}
        )

        assert agent.has_tool("tool1")

        agent.remove_tool("tool1")
        assert not agent.has_tool("tool1")
        assert len(agent.tools) == 0

    def test_execute_sync_tool(self):
        """测试执行同步工具"""
        def sync_tool(x: int, y: int):
            return x + y

        agent = TestAgent(
            name="test",
            custom_tools={"add": sync_tool}
        )

        result = agent.execute_tool("add", x=3, y=5)
        # 注意：execute_tool是async的，但它内部会处理sync函数
        # 在实际测试中需要await
        # 这里为了简化，我们用pytest的async支持

    @pytest.mark.asyncio
    async def test_execute_sync_tool_async(self):
        """测试执行同步工具（异步版本）"""
        def sync_tool(x: int, y: int):
            return x + y

        agent = TestAgent(
            name="test",
            custom_tools={"add": sync_tool}
        )

        result = await agent.execute_tool("add", x=3, y=5)
        assert result == 8

    @pytest.mark.asyncio
    async def test_execute_async_tool(self):
        """测试执行异步工具"""
        async def async_tool(x: int):
            return x * 2

        agent = TestAgent(
            name="test",
            custom_tools={"double": async_tool}
        )

        result = await agent.execute_tool("double", x=5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool(self):
        """测试执行不存在的工具"""
        agent = TestAgent(name="test")

        with pytest.raises(ValueError, match="Tool 'nonexistent' not found"):
            await agent.execute_tool("nonexistent")

    def test_get_tool_descriptions(self):
        """测试获取工具描述"""
        def tool1():
            """This is tool 1"""
            pass

        def tool2():
            """This is tool 2
            with multiple lines"""
            pass

        agent = TestAgent(
            name="test",
            custom_tools={
                "tool1": tool1,
                "tool2": tool2
            }
        )

        descriptions = agent.get_tool_descriptions()

        assert "tool1" in descriptions
        assert "tool2" in descriptions
        assert "This is tool 1" in descriptions
        assert "This is tool 2" in descriptions

    def test_get_tool_schemas(self):
        """测试获取工具schemas"""
        # 注册工具到Registry
        @ToolRegistry.register("schema_tool")
        def st(x: str, y: int = 10):
            """Schema test tool"""
            pass

        agent = TestAgent(name="test", tools=["schema_tool"])

        schemas = agent.get_tool_schemas()

        assert len(schemas) == 1
        assert schemas[0]["name"] == "schema_tool"
        assert "parameters" in schemas[0]

    def test_build_graph_not_implemented(self):
        """测试未实现build_graph的Agent"""
        class UnimplementedAgent(AgentBase):
            pass

        agent = UnimplementedAgent(name="unimplemented")

        with pytest.raises(NotImplementedError):
            agent.build_graph()

    def test_agent_repr(self):
        """测试Agent的字符串表示"""
        agent = TestAgent(name="test")

        repr_str = repr(agent)
        assert "TestAgent" in repr_str
        assert "test" in repr_str

        str_str = str(agent)
        assert "test Agent" in str_str

    def test_has_tool(self):
        """测试检查工具是否存在"""
        def tool1():
            pass

        agent = TestAgent(
            name="test",
            custom_tools={"tool1": tool1}
        )

        assert agent.has_tool("tool1") is True
        assert agent.has_tool("tool2") is False

    def test_list_tools(self):
        """测试列出所有工具"""
        @ToolRegistry.register("t1")
        def tool1():
            pass

        @ToolRegistry.register("t2")
        def tool2():
            pass

        agent = TestAgent(name="test", tools=["t1", "t2"])

        tools_list = agent.list_tools()
        assert isinstance(tools_list, list)
        assert len(tools_list) == 2
        assert "t1" in tools_list
        assert "t2" in tools_list

    def test_load_nonexistent_tool_warning(self):
        """测试加载不存在的工具会发出警告"""
        # 这个测试验证即使工具不存在，Agent也能正常初始化
        # 只是会发出警告日志
        agent = TestAgent(
            name="test",
            tools=["nonexistent_tool"]
        )

        # Agent应该正常创建，但没有加载任何工具
        assert len(agent.tools) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
