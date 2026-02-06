"""
MCP (Model Context Protocol) server for Doug.

Serves Doug's repository querying capabilities as MCP tools
for AI coding assistants like Claude.

Requires optional dependency:
    pip install doug[mcp]

I'm the bridge between Doug's brain and Claude's curiosity.
Ask me anything about your repos — I won't even charge a consulting fee.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

from doug.config import DougConfig

logger = logging.getLogger(__name__)


def _check_mcp_dependencies() -> Tuple[bool, str]:
    """Check if MCP dependencies are installed."""
    try:
        import mcp  # noqa: F401
        return True, "MCP dependencies available"
    except ImportError:
        return False, (
            "MCP dependencies not installed. "
            "Install with: pip install doug[mcp]"
        )


class DougMCPServer:
    """MCP server that exposes Doug's query tools.

    Tools exposed:
        - search_repos: Search across all indexed repos
        - list_apis: List API endpoints
        - repo_summary: Get repo summary
        - repo_detail: Get specific section of a repo
        - find_file: Find files by pattern
        - semantic_search: RAG search (if available)
        - generate_context: Generate a context document
    """

    def __init__(self, config: Optional[DougConfig] = None):
        self.config = config or DougConfig()

    def run_stdio(self) -> None:
        """Run the MCP server using stdio transport (for Claude Code)."""
        ok, msg = _check_mcp_dependencies()
        if not ok:
            raise RuntimeError(msg)

        import asyncio

        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        import mcp.types as types

        server = Server("doug")
        self._register_tools(server, types)

        async def _run() -> None:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())

        asyncio.run(_run())

    def run_sse(self, host: str = "localhost", port: int = 3333) -> None:
        """Run the MCP server using SSE transport."""
        ok, msg = _check_mcp_dependencies()
        if not ok:
            raise RuntimeError(msg)

        import asyncio

        from mcp.server import Server
        import mcp.types as types

        server = Server("doug")
        self._register_tools(server, types)

        try:
            from mcp.server.sse import SseServerTransport
            from starlette.applications import Starlette
            from starlette.routing import Route
            import uvicorn

            sse = SseServerTransport("/messages")

            async def handle_sse(request: Any) -> Any:
                async with sse.connect_sse(
                    request.scope, request.receive, request._send
                ) as streams:
                    await server.run(
                        streams[0], streams[1],
                        server.create_initialization_options(),
                    )

            app = Starlette(routes=[
                Route("/sse", endpoint=handle_sse),
                Route("/messages", endpoint=sse.handle_post_message, methods=["POST"]),
            ])

            print(f"Doug MCP server running on http://{host}:{port}")
            print(f"  SSE endpoint: http://{host}:{port}/sse")
            uvicorn.run(app, host=host, port=port)

        except ImportError:
            raise RuntimeError(
                "SSE transport requires additional dependencies: "
                "pip install starlette uvicorn"
            )

    def _register_tools(self, server: Any, types: Any) -> None:
        """Register all Doug tools with the MCP server."""
        from doug.ai_query import AIQueryTool
        from doug.context_generator import ContextGenerator

        query_tool = AIQueryTool(config=self.config)
        context_gen = ContextGenerator(config=self.config)

        @server.list_tools()
        async def list_tools() -> list:
            return [
                types.Tool(
                    name="search_repos",
                    description=(
                        "Search across all indexed repositories for files, "
                        "APIs, classes, and readme content"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search term",
                            },
                            "scope": {
                                "type": "string",
                                "enum": ["all", "files", "apis", "classes"],
                                "description": "Search scope (default: all)",
                            },
                        },
                        "required": ["query"],
                    },
                ),
                types.Tool(
                    name="list_apis",
                    description=(
                        "List API endpoints across all repos or filtered by repo name"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo_name": {
                                "type": "string",
                                "description": "Filter by repository name (optional)",
                            },
                        },
                    },
                ),
                types.Tool(
                    name="repo_summary",
                    description=(
                        "Get a summary of a specific repository including "
                        "stats, build info, and readme"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo_name": {
                                "type": "string",
                                "description": "Repository name",
                            },
                        },
                        "required": ["repo_name"],
                    },
                ),
                types.Tool(
                    name="repo_detail",
                    description=(
                        "Get detailed data for a specific section of a repository"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo_name": {
                                "type": "string",
                                "description": "Repository name",
                            },
                            "section": {
                                "type": "string",
                                "enum": [
                                    "apis", "services", "models", "controllers",
                                    "configs", "structure", "build", "summary", "readme",
                                ],
                                "description": "Section to retrieve",
                            },
                        },
                        "required": ["repo_name", "section"],
                    },
                ),
                types.Tool(
                    name="find_file",
                    description="Find files matching a pattern in a repository",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo_name": {
                                "type": "string",
                                "description": "Repository name",
                            },
                            "pattern": {
                                "type": "string",
                                "description": "File name or path pattern",
                            },
                        },
                        "required": ["repo_name", "pattern"],
                    },
                ),
                types.Tool(
                    name="semantic_search",
                    description=(
                        "Semantic search across indexed code using RAG "
                        "(requires doug[rag])"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Natural language search query",
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "Number of results (default: 10)",
                            },
                            "repo_filter": {
                                "type": "string",
                                "description": "Filter by repo name (optional)",
                            },
                        },
                        "required": ["query"],
                    },
                ),
                types.Tool(
                    name="generate_context",
                    description=(
                        "Generate a comprehensive context document "
                        "for AI conversations"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repos": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Specific repos to include (default: all)",
                            },
                            "max_tokens": {
                                "type": "integer",
                                "description": "Maximum estimated tokens for output",
                            },
                        },
                    },
                ),
            ]

        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list:
            result = self._handle_tool_call(
                name, arguments, query_tool, context_gen
            )
            return [types.TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str),
            )]

    def _handle_tool_call(
        self,
        name: str,
        arguments: Dict[str, Any],
        query_tool: Any,
        context_gen: Any,
    ) -> Any:
        """Synchronous tool call handler.

        Dispatches to the appropriate query method based on tool name.
        """
        try:
            if name == "search_repos":
                return query_tool.search(
                    arguments["query"],
                    scope=arguments.get("scope", "all"),
                )

            elif name == "list_apis":
                return query_tool.list_apis(
                    repo_name=arguments.get("repo_name"),
                )

            elif name == "repo_summary":
                return query_tool.repo_summary(arguments["repo_name"])

            elif name == "repo_detail":
                return query_tool.repo_detail(
                    arguments["repo_name"],
                    arguments["section"],
                )

            elif name == "find_file":
                return query_tool.find_file(
                    arguments["repo_name"],
                    arguments["pattern"],
                )

            elif name == "semantic_search":
                try:
                    from doug.rag.rag_engine import RAGEngine
                    engine = RAGEngine(config=self.config)
                    return engine.search(
                        arguments["query"],
                        top_k=arguments.get("top_k", 10),
                        repo_filter=arguments.get("repo_filter"),
                    )
                except ImportError:
                    return {
                        "error": "RAG not available. Install with: pip install doug[rag]"
                    }

            elif name == "generate_context":
                return {
                    "document": context_gen.generate_context_document(
                        repos=arguments.get("repos"),
                        max_tokens=arguments.get("max_tokens"),
                    ),
                }

            else:
                return {"error": f"Unknown tool: {name}"}

        except Exception as e:
            logger.exception("Tool call error: %s", e)
            return {"error": str(e)}
