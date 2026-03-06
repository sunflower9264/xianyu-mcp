"""
Xianyu MCP Server - MCP service for Xianyu (闲鱼) with Playwright browser automation.

This server provides tools for interacting with Xianyu platform through browser automation,
including login management, goods search, and detail retrieval.
"""

import asyncio
import json
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import (
    AudioContent,
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    TextContent,
    Tool,
)

from xianyu_mcp.config import get_settings
from xianyu_mcp.infrastructure.api import close_api_client
from xianyu_mcp.infrastructure.browser import get_browser_manager
from xianyu_mcp.logging import init_logging
from xianyu_mcp.mcp.tools import ALL_TOOLS

# Initialize logging
logger = init_logging()


# Create MCP server instance
server = Server("xianyu-mcp")


class StreamableHTTPASGIApp:
    """ASGI adapter for Streamable HTTP session manager."""

    def __init__(self, session_manager: StreamableHTTPSessionManager):
        self.session_manager = session_manager

    async def __call__(self, scope, receive, send) -> None:  # pragma: no cover
        await self.session_manager.handle_request(scope, receive, send)


def _normalize_http_path(path: str) -> str:
    """Normalize HTTP path for route registration."""
    cleaned = (path or "").strip()
    if not cleaned:
        return "/mcp"
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    return cleaned


def create_streamable_http_app(path: str):
    """Create a Starlette app for Streamable HTTP MCP transport."""
    from starlette.applications import Starlette
    from starlette.routing import Route

    route_path = _normalize_http_path(path)
    session_manager = StreamableHTTPSessionManager(app=server)
    streamable_http_app = StreamableHTTPASGIApp(session_manager)

    return Starlette(
        routes=[
            Route(
                route_path,
                endpoint=streamable_http_app,
                methods=["GET", "POST", "DELETE"],
            )
        ],
        lifespan=lambda _app: session_manager.run(),
    )


def _get_tool_definitions() -> list[Tool]:
    """Get tool definitions for MCP registration."""
    tools = []
    for tool_def in ALL_TOOLS:
        tool = Tool(
            name=tool_def["name"],
            description=tool_def["description"],
            inputSchema=tool_def["inputSchema"],
        )
        tools.append(tool)
    return tools


def _is_content_block_list(value: Any) -> bool:
    """Return True when value looks like MCP unstructured content blocks."""
    if not isinstance(value, list):
        return False

    allowed_dict_types = {"text", "image", "audio", "resource"}
    for item in value:
        if isinstance(item, (TextContent, ImageContent, AudioContent, EmbeddedResource)):
            continue
        if isinstance(item, dict) and item.get("type") in allowed_dict_types:
            continue
        return False
    return True


async def _run_cookie_auto_sync_loop() -> None:
    """Run periodic cookie sync in background."""
    settings = get_settings()
    browser_manager = get_browser_manager()
    interval = settings.cookie_sync_interval_seconds
    timeout = settings.cookie_sync_timeout_seconds

    logger.info(
        "Cookie auto-sync loop started "
        f"(interval={interval}s, timeout={timeout}s)"
    )

    try:
        while True:
            result = await browser_manager.sync_cookies_once(timeout_seconds=timeout)
            status = result.get("status", "unknown")

            if status == "synced":
                logger.info(
                    "Cookie auto-sync success "
                    f"(cookie_count={result.get('cookie_count', 0)})"
                )
            elif status == "logged_out_cleared":
                logger.warning("Cookie auto-sync detected logged-out state and cleared local session")
            elif status == "skipped":
                logger.warning(f"Cookie auto-sync skipped: {result.get('message', '')}")
            else:
                logger.warning(f"Cookie auto-sync check failed: {result.get('message', '')}")

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("Cookie auto-sync loop cancelled")
        raise
    except Exception as e:
        logger.warning(f"Cookie auto-sync loop crashed unexpectedly: {e}")
        raise


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return list of available tools."""
    logger.debug("Listing tools")
    return _get_tool_definitions()


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Handle tool calls."""
    logger.info(f"Tool called: {name} with arguments: {arguments}")
    settings = get_settings()
    timeout_seconds = settings.mcp_tool_timeout_seconds

    # Find the tool handler
    handler = None
    for tool_def in ALL_TOOLS:
        if tool_def["name"] == name:
            handler = tool_def["handler"]
            break

    if handler is None:
        logger.error(f"Unknown tool: {name}")
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": True,
                "message": f"Unknown tool: {name}",
            }, ensure_ascii=False)
        )]

    try:
        # Call the handler (may be sync or async)
        import inspect
        if inspect.iscoroutinefunction(handler):
            result = await asyncio.wait_for(
                handler(**arguments),
                timeout=timeout_seconds,
            )
        else:
            # Run sync function in executor to avoid blocking
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: handler(**arguments)),
                timeout=timeout_seconds,
            )

        logger.debug(f"Tool result: {result}")

        # Let MCP-native content pass through (e.g. ImageContent blocks).
        if isinstance(result, (CallToolResult, tuple)) or _is_content_block_list(result):
            return result

        # Keep backward-compatible text JSON output for structured dict results.
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

    except asyncio.TimeoutError:
        logger.error(f"Tool call timed out: {name} (timeout={timeout_seconds}s)")
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": True,
                "message": f"Tool call timed out after {timeout_seconds} seconds",
                "tool": name,
                "error_code": "TIMEOUT",
                "timeout_seconds": timeout_seconds,
            }, ensure_ascii=False)
        )]
    except Exception as e:
        logger.error(f"Error calling tool {name}: {e}", exc_info=True)
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": True,
                "message": f"Error calling tool: {e}",
                "tool": name,
            }, ensure_ascii=False)
        )]


async def run_server() -> None:
    """Run the MCP server."""
    settings = get_settings()
    logger.info(f"Starting Xianyu MCP Server (log level: {settings.log_level})")
    logger.info(f"Headless mode: {settings.headless}")
    logger.info(f"MCP tool timeout: {settings.mcp_tool_timeout_seconds}s")
    logger.info(f"MCP transport: {settings.mcp_transport}")
    logger.info("Browser session mode: non-persistent (fresh session per server run)")
    logger.info(
        f"Cookie auto-sync: enabled={settings.cookie_auto_sync_enabled}, "
        f"interval={settings.cookie_sync_interval_seconds}s, "
        f"timeout={settings.cookie_sync_timeout_seconds}s"
    )

    cookie_sync_task: asyncio.Task | None = None

    # Pre-initialize browser on startup
    try:
        browser_manager = get_browser_manager()
        logger.info("Pre-initializing browser...")
        await browser_manager.start()
        logger.info("Browser initialized successfully")
    except Exception as e:
        logger.warning(f"Could not pre-initialize browser: {e}")

    if settings.cookie_auto_sync_enabled:
        cookie_sync_task = asyncio.create_task(_run_cookie_auto_sync_loop())

    try:
        if settings.mcp_transport == "stdio":
            async with stdio_server() as (read_stream, write_stream):
                logger.info("MCP server running on stdio")
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options()
                )
        elif settings.mcp_transport == "streamable_http":
            import uvicorn

            http_path = _normalize_http_path(settings.mcp_streamable_http_path)
            app = create_streamable_http_app(http_path)
            logger.info(
                "MCP server running on Streamable HTTP at "
                f"http://{settings.mcp_http_host}:{settings.mcp_http_port}{http_path}"
            )

            config = uvicorn.Config(
                app,
                host=settings.mcp_http_host,
                port=settings.mcp_http_port,
                log_level=settings.log_level.lower(),
            )
            await uvicorn.Server(config).serve()
        else:
            raise ValueError(f"Unsupported MCP transport: {settings.mcp_transport}")
    finally:
        if cookie_sync_task is not None:
            cookie_sync_task.cancel()
            try:
                await cookie_sync_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Error during cookie auto-sync task shutdown: {e}")

        # Explicit async cleanup to avoid relying solely on atexit fallbacks.
        try:
            await get_browser_manager().close()
        except Exception as e:
            logger.warning(f"Error during browser cleanup: {e}")

        try:
            await close_api_client()
        except Exception as e:
            logger.warning(f"Error during API client cleanup: {e}")

        logger.info("Runtime resources cleaned up")


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Server shutdown complete")


if __name__ == "__main__":
    main()
