import asyncio
import logging
import os
from typing import List, Dict, Union, Optional
from contextlib import AsyncExitStack
from enum import Enum

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

# LangChain imports
from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage, AIMessage

from src.core.llm.client import LLMBase
from src.utils.helpers import *

logging.basicConfig(
    level=logging.INFO,  # 可根据需要改为 DEBUG
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class MCPClient:
    """
    MCP Client that connects to MCP servers and manages tool discovery and execution.
    Uses dependency injection to work with any LLMBase implementation.
    
    Features:
    - Multi-server connection support (stdio, sse, streamable-http)
    - Dynamic tool discovery and management
    - Tool execution with proper error handling
    - Integration with LLM for agentic workflows
    """

    def __init__(
        self,
        llm_client: LLMBase,
        server_config: dict,
        system_prompt: Optional[str] = None
    ):
        """
        Initialize MCP Client with dependency injection.

        Args:
            llm_client: LLMBase instance for LLM operations
            server_config: Dictionary of MCP server configurations
            system_prompt: Custom system prompt for tool interactions
        """
        self.llm_client = llm_client
        self.server_config = server_config
        self.session_dict: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        
        # Tool management
        self.tools: List[Dict] = []
        self.tool_name_to_session: Dict[str, tuple] = {}
        
        # System prompt configuration
        self.system_prompt = system_prompt or self._get_default_system_prompt()

    def _get_default_system_prompt(self) -> str:
        """获取默认的system prompt"""
        return """You are a helpful AI assistant with access to various tools through MCP (Model Context Protocol) servers.

# Instructions:
- Use the available tools to gather information and help users with their queries
- Always explain what you're doing when using tools
- Provide clear, accurate, and helpful responses
- If you need to use multiple tools, explain your reasoning
- Cite sources when presenting factual information

# Available Tools:
You have access to tools that will be provided dynamically. Use them appropriately to answer user questions.

Be helpful, accurate, and transparent about your capabilities and limitations."""

    async def initialize(self):
        """Initialize MCP client by connecting to servers and discovering tools."""
        await self.connect_to_server()
        await self._discover_tools()
        self._update_system_prompt_with_tools()

    def get_tools_description(self) -> str:
        """获取可用工具的描述，用于动态更新system prompt"""
        if not self.tools:
            return "No tools are currently available."
        
        descriptions = []
        for tool in self.tools:
            descriptions.append(f"- {tool['name']}: {tool['description']}")
        
        return "Available tools:\n" + "\n".join(descriptions)

    def _update_system_prompt_with_tools(self):
        """根据可用工具更新system prompt"""
        tools_desc = self.get_tools_description()
        self.system_prompt = f"{self._get_default_system_prompt()}\n\n{tools_desc}"
        logger.info(f"System prompt updated with {len(self.tools)} tools")

    async def cleanup(self):
        """Clean up resources and close connections."""
        try:
            await self.exit_stack.aclose()
            logger.info("MCP resources cleaned up successfully.")
        except Exception as e:
            logger.exception("Error during MCP cleanup")

    def get_available_tools(self) -> List[Dict]:
        """Get list of available tools."""
        return self.tools.copy()

    def get_tool_count(self) -> int:
        """Get number of available tools."""
        return len(self.tools)

    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a specific tool is available."""
        return tool_name in self.tool_name_to_session

    async def connect_to_server(self):
        """
        Connect to all configured MCP servers.
        Supports stdio, sse, and streamable-http transports.
        """
        try:
            for name, config in self.server_config.items():
                connection_type = config.get("type", "")
                logger.info(f"Connecting to server '{name}' with type: {connection_type}")

                session = None
                try:
                    if connection_type == "stdio":
                        server_params = StdioServerParameters(
                            command=config.get("command"),
                            args=config.get("args"),
                            env=config.get("env"),
                        )
                        stdio_transport = await self.exit_stack.enter_async_context(
                            stdio_client(server_params))
                        read_stream, write_stream = stdio_transport
                        session = await self.exit_stack.enter_async_context(
                            ClientSession(read_stream, write_stream))
                        await session.initialize()
                        logger.info(f"Session '{name}' (stdio) initialized successfully.")
                        
                    elif connection_type == "sse":
                        streams = await self.exit_stack.enter_async_context(
                            sse_client(config.get("url")))
                        session = await self.exit_stack.enter_async_context(
                            ClientSession(*streams))
                        await session.initialize()
                        logger.info(f"Session '{name}' (sse) initialized successfully.")

                    elif connection_type == 'streamable-http':
                        read_stream, write_stream, _= await self.exit_stack.enter_async_context(
                            streamablehttp_client(config.get("url")))
                        session = await self.exit_stack.enter_async_context(
                            ClientSession(read_stream, write_stream))
                        await session.initialize()
                        logger.info(f"Session '{name}' (streamable-http) initialized successfully.")

                    else:
                        logger.error(f"Error: undefined connection type '{connection_type}'")
                        continue
                        
                    if session:
                        self.session_dict[name] = session
                        
                except Exception as e:
                    logger.error(f"Failed to initialize session '{name}': {e}")
                    continue

        except Exception as e:
            logger.exception("Failed to connect to servers.")
            raise 

    async def _discover_tools(self):
        """
        Discover all tools from connected MCP servers.
        Converts MCP tool schemas to appropriate format for LLM usage.
        """
        self.tools = []
        self.tool_name_to_session = {}
        
        for server_name, session in self.session_dict.items():
            try:
                response = await session.list_tools()
                logger.info(f"Discovered {len(response.tools)} tools from server '{server_name}'")

                for mcp_tool in response.tools:
                    # Convert MCP tool to LLM-compatible format
                    tool_def = self._convert_tool_format(mcp_tool)
                    self.tools.append(tool_def)
                    self.tool_name_to_session[mcp_tool.name] = (server_name, session)
                    logger.debug(f"  - {mcp_tool.name}: {mcp_tool.description}")

            except Exception as e:
                logger.error(f"Failed to list tools from server '{server_name}': {e}")

    def _convert_tool_format(self, mcp_tool) -> Dict:
        """Convert MCP tool to LLM-compatible format."""
        return {
            "name": mcp_tool.name,
            "description": mcp_tool.description or f"Tool: {mcp_tool.name}",
            "input_schema": mcp_tool.inputSchema
        }

    async def execute_tool(self, tool_name: str, tool_input: Dict) -> str:
        """
        Execute a tool via its MCP server session.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool

        Returns:
            Tool execution result as string
        """
        if tool_name not in self.tool_name_to_session:
            return f"Error: Tool '{tool_name}' not found"

        server_name, session = self.tool_name_to_session[tool_name]

        try:
            logger.info(f"Executing tool '{tool_name}' on server '{server_name}' with input: {tool_input}")
            result = await session.call_tool(tool_name, tool_input)

            # Extract text content from result
            if hasattr(result, 'content') and result.content:
                if isinstance(result.content, list):
                    # Concatenate all text content
                    text_parts = []
                    for content in result.content:
                        if hasattr(content, 'text'):
                            text_parts.append(content.text)
                    return "\n".join(text_parts) if text_parts else str(result.content)
                else:
                    return str(result.content)

            return str(result)

        except Exception as e:
            logger.exception(f"Error executing tool '{tool_name}': {e}")
            return f"Error executing tool: {str(e)}"

    async def process_query_with_tools(
        self, 
        query: str, 
        session_id: str = "mcp_session",
        max_iterations: int = 10
    ) -> str:
        """
        Process a query using LLM with MCP tools in an agentic loop.

        Args:
            query: User query to process
            session_id: Session ID for conversation history
            max_iterations: Maximum number of tool use iterations

        Returns:
            Final response from LLM
        """
        if not self.tools:
            logger.warning("No tools available. Processing query without tools.")
            return await self._process_without_tools(query, session_id)

        return await self._process_with_tools(query, session_id, max_iterations)

    async def _process_without_tools(self, query: str, session_id: str) -> str:
        """Process query without MCP tools using base LLM."""
        try:
            response = await self.llm_client.async_call_llm_chain(
                role="chat",
                input_prompt=query,
                session_id=session_id
            )
            return response
        except Exception as e:
            logger.error(f"Error processing query without tools: {e}")
            return f"Error processing query: {str(e)}"

    async def _process_with_tools(self, query: str, session_id: str, max_iterations: int) -> str:
        """
        Process query using LLM with MCP tools in an agentic loop.
        Uses LangChain for tool calling.
        """
        # Build messages for tool-calling conversation
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=query)
        ]
        
        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            logger.info(f"--- MCP Tool Iteration {iteration} ---")

            try:
                # Get LLM client with tools
                llm_with_tools = self._get_llm_with_tools()
                
                # Call LLM with current messages
                response = await self._invoke_llm_async(llm_with_tools, messages)

                # Check for tool calls
                if hasattr(response, 'tool_calls') and response.tool_calls:
                    # Add AI message to conversation
                    messages.append(response)

                    # Process all tool calls
                    for tool_call in response.tool_calls:
                        tool_name = tool_call.get('name') if isinstance(tool_call, dict) else tool_call.name
                        tool_input = tool_call.get('args', {}) if isinstance(tool_call, dict) else tool_call.args
                        tool_call_id = tool_call.get('id') if isinstance(tool_call, dict) else tool_call.id

                        logger.info(f"Tool use: {tool_name}")
                        logger.debug(f"Tool input: {tool_input}")

                        # Execute the tool
                        result = await self.execute_tool(tool_name, tool_input)

                        # Add tool message with result
                        messages.append(ToolMessage(
                            content=result,
                            tool_call_id=tool_call_id
                        ))
                else:
                    # No tool calls - we have a final answer
                    final_answer = response.content
                    logger.info(f"Final answer received after {iteration} iteration(s)")
                    
                    # Store conversation in LLM client's history
                    self._store_conversation_in_history(query, final_answer, session_id)
                    
                    return final_answer

            except Exception as e:
                logger.exception(f"Error in iteration {iteration}: {e}")
                return f"Error processing query: {str(e)}"

        logger.warning(f"Reached maximum iterations ({max_iterations})")
        return "Maximum iterations reached without final answer."

    def _get_llm_with_tools(self):
        """Get LLM client with bound tools."""
        llm_client = self.llm_client.get_chat_model()
        if self.tools and hasattr(llm_client, 'bind_tools'):
            return llm_client.bind_tools(self.tools)
        return llm_client

    async def _invoke_llm_async(self, llm_with_tools, messages):
        """Invoke LLM with async support."""
        try:
            if hasattr(llm_with_tools, 'ainvoke'):
                return await llm_with_tools.ainvoke(messages)
            else:
                # Fallback to sync invoke in executor
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None,
                    lambda: llm_with_tools.invoke(messages)
                )
        except Exception as e:
            logger.error(f"Error invoking LLM: {e}")
            raise

    def _store_conversation_in_history(self, query: str, response: str, session_id: str):
        """Store the conversation in LLM client's message history."""
        try:
            # Add human message
            self.llm_client.add_message_to_history(
                session_id=session_id,
                message=HumanMessage(content=query)
            )
            # Add AI response
            self.llm_client.add_message_to_history(
                session_id=session_id,
                message=AIMessage(content=response)
            )
        except Exception as e:
            logger.warning(f"Failed to store conversation in history: {e}")


