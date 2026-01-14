"""
Tool Registry 单元测试
"""

import pytest
from src.agents.tools.registry import ToolRegistry


class TestToolRegistry:
    """Tool Registry测试类"""

    def setup_method(self):
        """每个测试前清空registry"""
        ToolRegistry.clear()

    def test_register_sync_tool(self):
        """测试注册同步工具"""
        @ToolRegistry.register("test_sync")
        def sync_tool(param: str):
            """Test sync tool"""
            return param

        assert "test_sync" in ToolRegistry.list_tools()
        assert ToolRegistry.count() == 1

        tool_func = ToolRegistry.get("test_sync")
        assert tool_func is not None
        assert tool_func("hello") == "hello"

    def test_register_async_tool(self):
        """测试注册异步工具"""
        @ToolRegistry.register("test_async")
        async def async_tool(param: str):
            """Test async tool"""
            return param

        assert "test_async" in ToolRegistry.list_tools()

        tool_info = ToolRegistry.get_tool_info("test_async")
        assert tool_info is not None
        assert tool_info["is_async"] is True

    def test_register_without_name(self):
        """测试不指定名称的注册（使用函数名）"""
        @ToolRegistry.register()
        def my_function(x: int):
            """My function"""
            return x * 2

        assert "my_function" in ToolRegistry.list_tools()
        tool = ToolRegistry.get("my_function")
        assert tool(5) == 10

    def test_get_nonexistent_tool(self):
        """测试获取不存在的工具"""
        tool = ToolRegistry.get("nonexistent")
        assert tool is None

    def test_list_tools(self):
        """测试列出所有工具"""
        @ToolRegistry.register("tool1")
        def t1():
            """Tool 1"""
            pass

        @ToolRegistry.register("tool2")
        def t2():
            """Tool 2"""
            pass

        tools = ToolRegistry.list_tools()
        assert isinstance(tools, dict)
        assert len(tools) == 2
        assert "tool1" in tools
        assert "tool2" in tools
        assert tools["tool1"] == "Tool 1"
        assert tools["tool2"] == "Tool 2"

    def test_get_tool_schema(self):
        """测试获取工具的OpenAI schema"""
        @ToolRegistry.register("search")
        async def search(query: str, limit: int = 10):
            """Search documents"""
            pass

        schema = ToolRegistry.get_tool_schema("search")

        assert schema is not None
        assert schema["name"] == "search"
        assert schema["description"] == "Search documents"
        assert "parameters" in schema

        params = schema["parameters"]
        assert params["type"] == "object"
        assert "query" in params["properties"]
        assert "limit" in params["properties"]

        # query是必需参数
        assert "query" in params["required"]
        # limit有默认值，不是必需参数
        assert "limit" not in params["required"]

        # 检查类型
        assert params["properties"]["query"]["type"] == "string"
        assert params["properties"]["limit"]["type"] == "integer"

    def test_get_all_schemas(self):
        """测试获取所有工具的schemas"""
        @ToolRegistry.register("tool1")
        def t1(x: str):
            """Tool 1"""
            pass

        @ToolRegistry.register("tool2")
        def t2(y: int):
            """Tool 2"""
            pass

        schemas = ToolRegistry.get_all_schemas()

        assert len(schemas) == 2
        assert all(isinstance(s, dict) for s in schemas)
        assert all("name" in s for s in schemas)

    def test_python_type_to_json(self):
        """测试Python类型转换为JSON类型"""
        assert ToolRegistry._python_type_to_json(str) == "string"
        assert ToolRegistry._python_type_to_json(int) == "integer"
        assert ToolRegistry._python_type_to_json(float) == "number"
        assert ToolRegistry._python_type_to_json(bool) == "boolean"
        assert ToolRegistry._python_type_to_json(list) == "array"
        assert ToolRegistry._python_type_to_json(dict) == "object"

    def test_clear(self):
        """测试清空registry"""
        @ToolRegistry.register("tool1")
        def t1():
            pass

        @ToolRegistry.register("tool2")
        def t2():
            pass

        assert ToolRegistry.count() == 2

        ToolRegistry.clear()
        assert ToolRegistry.count() == 0
        assert len(ToolRegistry.list_tools()) == 0

    def test_tool_with_complex_types(self):
        """测试复杂类型参数的工具"""
        from typing import List, Dict, Optional

        @ToolRegistry.register("complex_tool")
        async def complex_tool(
            items: List[str],
            metadata: Dict[str, int],
            optional_param: Optional[str] = None
        ):
            """Complex tool with various types"""
            pass

        schema = ToolRegistry.get_tool_schema("complex_tool")

        assert schema is not None
        params = schema["parameters"]["properties"]

        assert params["items"]["type"] == "array"
        assert params["metadata"]["type"] == "object"
        assert params["optional_param"]["type"] == "string"

    def test_get_tool_info(self):
        """测试获取工具完整信息"""
        @ToolRegistry.register("info_test")
        async def info_test(x: int):
            """Test tool for info"""
            return x

        info = ToolRegistry.get_tool_info("info_test")

        assert info is not None
        assert "func" in info
        assert "signature" in info
        assert "description" in info
        assert "is_async" in info
        assert info["is_async"] is True
        assert info["description"] == "Test tool for info"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
