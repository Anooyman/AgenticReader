# scraper/mcp_server/server.py
"""MCP Server implementation for web scraping tools"""
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from scraper.mcp_server.tools import (
    scrape_url_tool,
    scrape_batch_tool,
    download_resources_tool
)
from typing import Any
import json


def create_mcp_server() -> Server:
    """Create and configure MCP server with scraping tools

    Returns:
        Configured MCP Server instance
    """
    server = Server("mcp-scraper")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available scraping tools"""
        return [
            Tool(
                name="scrape_url",
                description="Scrape content from a single URL with anti-bot detection",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target URL to scrape"},
                        "content_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Types to extract: html, text, json, screenshot",
                            "default": ["html", "text"]
                        },
                        "wait_for": {"type": "string", "description": "CSS selector to wait for"},
                        "headless": {"type": "boolean", "default": True},
                        "timeout": {"type": "integer", "default": 30000}
                    },
                    "required": ["url"]
                }
            ),
            Tool(
                name="scrape_batch",
                description="Scrape multiple URLs in batch",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of URLs to scrape"
                        },
                        "content_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": ["html", "text"]
                        },
                        "concurrent_limit": {"type": "integer", "default": 3},
                        "delay_between": {"type": "integer", "default": 2000}
                    },
                    "required": ["urls"]
                }
            ),
            Tool(
                name="download_resources",
                description="Download resources (images, PDFs, videos) from a URL",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Target URL"},
                        "resource_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Resource types: images, pdfs, videos, all",
                            "default": ["images"]
                        },
                        "selector": {"type": "string", "description": "CSS selector to filter"},
                        "max_files": {"type": "integer", "default": 50}
                    },
                    "required": ["url"]
                }
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: Any) -> list[TextContent]:
        """Execute a scraping tool

        Args:
            name: Tool name (scrape_url, scrape_batch, download_resources)
            arguments: Tool arguments as dictionary

        Returns:
            List of text content with results
        """
        result = None

        if name == "scrape_url":
            result = await scrape_url_tool(**arguments)
        elif name == "scrape_batch":
            result = await scrape_batch_tool(**arguments)
        elif name == "download_resources":
            result = await download_resources_tool(**arguments)
        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


async def main():
    """Run the MCP server"""
    server = create_mcp_server()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
