"""MCP (Model Context Protocol) client — manage MCP servers and bridge their tools."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Optional

from openlama.config import DATA_DIR
from openlama.logger import get_logger

logger = get_logger("mcp")

_MCP_CONFIG_FILE = DATA_DIR / "mcp.json"

# Active server instances
_servers: dict[str, "MCPServer"] = {}


class MCPServer:
    """Represents a connected MCP server process."""

    def __init__(self, name: str, command: str, args: list[str], env: dict[str, str] | None = None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env or {}
        self.process: asyncio.subprocess.Process | None = None
        self.tools: list[dict] = []
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._initialized = False

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def start(self) -> bool:
        """Start the MCP server process and initialize the connection."""
        try:
            env = {**os.environ, **self.env}
            self.process = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            logger.info("started MCP server '%s' (PID %s)", self.name, self.process.pid)

            # Start reader task for responses
            self._reader_task = asyncio.create_task(self._read_responses())

            # Send initialize request
            result = await self._request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "openlama", "version": "0.1.0"},
            })

            if result is None:
                logger.error("MCP server '%s' did not respond to initialize", self.name)
                await self.stop()
                return False

            # Send initialized notification
            await self._notify("notifications/initialized", {})
            self._initialized = True

            # Discover tools
            await self.refresh_tools()
            logger.info("MCP server '%s' initialized with %d tools", self.name, len(self.tools))
            return True

        except FileNotFoundError:
            logger.error("MCP server command not found: %s", self.command)
            return False
        except Exception as e:
            logger.error("failed to start MCP server '%s': %s", self.name, e)
            return False

    async def stop(self):
        """Stop the MCP server process."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            except Exception as e:
                logger.error("error stopping MCP server '%s': %s", self.name, e)

        self.process = None
        self._initialized = False
        self.tools = []
        # Cancel all pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        logger.info("stopped MCP server '%s'", self.name)

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.returncode is None and self._initialized

    async def _send(self, message: dict):
        """Send a JSON-RPC message to the server via stdin."""
        if not self.process or not self.process.stdin:
            return
        data = json.dumps(message) + "\n"
        self.process.stdin.write(data.encode())
        await self.process.stdin.drain()

    async def _request(self, method: str, params: dict, timeout: float = 30) -> Optional[Any]:
        """Send a JSON-RPC request and wait for the response."""
        req_id = self._next_id()
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[req_id] = future

        await self._send(message)

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning("MCP request timed out: %s.%s", self.name, method)
            self._pending.pop(req_id, None)
            return None

    async def _notify(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._send(message)

    async def _read_responses(self):
        """Read JSON-RPC responses from stdout."""
        if not self.process or not self.process.stdout:
            return

        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break

                line = line.decode().strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                req_id = msg.get("id")
                if req_id is not None and req_id in self._pending:
                    future = self._pending.pop(req_id)
                    if not future.done():
                        if "error" in msg:
                            future.set_exception(
                                RuntimeError(f"MCP error: {msg['error']}")
                            )
                        else:
                            future.set_result(msg.get("result"))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("MCP reader error for '%s': %s", self.name, e)

    async def refresh_tools(self):
        """Fetch the list of tools from the server."""
        result = await self._request("tools/list", {})
        if result and "tools" in result:
            self.tools = result["tools"]
        else:
            self.tools = []

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the MCP server. Returns result as string."""
        result = await self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        }, timeout=120)

        if result is None:
            return f"MCP tool call failed: {self.name}/{tool_name} (timeout)"

        # Parse MCP tool result format
        content_parts = result.get("content", [])
        if isinstance(content_parts, list):
            texts = []
            for part in content_parts:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        texts.append(part.get("text", ""))
                    elif part.get("type") == "image":
                        texts.append(f"[IMAGE:{part.get('data', '')}]")
                elif isinstance(part, str):
                    texts.append(part)
            return "\n".join(texts) if texts else str(result)

        return str(result)


# ─── Config management ─────────────────────────────

def _load_mcp_config() -> dict:
    """Load MCP server configuration from mcp.json."""
    if not _MCP_CONFIG_FILE.exists():
        return {"servers": {}}
    try:
        with open(_MCP_CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if "servers" not in data:
            data = {"servers": data}
        return data
    except Exception as e:
        logger.error("failed to load mcp.json: %s", e)
        return {"servers": {}}


def _save_mcp_config(config: dict):
    """Save MCP config to mcp.json."""
    _MCP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_MCP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def add_server_config(name: str, command: str, args: list[str], env: dict | None = None):
    """Add or update an MCP server in the config file."""
    config = _load_mcp_config()
    entry: dict[str, Any] = {"command": command, "args": args}
    if env:
        entry["env"] = env
    config["servers"][name] = entry
    _save_mcp_config(config)
    logger.info("added MCP server config: %s", name)


def remove_server_config(name: str) -> bool:
    """Remove an MCP server from the config file."""
    config = _load_mcp_config()
    if name not in config.get("servers", {}):
        return False
    del config["servers"][name]
    _save_mcp_config(config)
    logger.info("removed MCP server config: %s", name)
    return True


def list_server_configs() -> dict:
    """List all configured MCP servers."""
    return _load_mcp_config().get("servers", {})


# ─── Server lifecycle ─────────────────────────────

async def start_server(name: str) -> bool:
    """Start a specific MCP server by name from config."""
    if name in _servers and _servers[name].alive:
        logger.info("MCP server '%s' already running", name)
        return True

    config = _load_mcp_config()
    server_conf = config.get("servers", {}).get(name)
    if not server_conf:
        logger.error("MCP server '%s' not found in config", name)
        return False

    server = MCPServer(
        name=name,
        command=server_conf["command"],
        args=server_conf.get("args", []),
        env=server_conf.get("env"),
    )

    if await server.start():
        _servers[name] = server
        return True
    return False


async def stop_server(name: str):
    """Stop a specific MCP server."""
    server = _servers.pop(name, None)
    if server:
        await server.stop()


async def start_all_servers():
    """Start all configured MCP servers."""
    config = _load_mcp_config()
    servers = config.get("servers", {})
    if not servers:
        return

    logger.info("starting %d MCP servers...", len(servers))
    for name in servers:
        try:
            await start_server(name)
        except Exception as e:
            logger.error("failed to start MCP server '%s': %s", name, e)


async def stop_all_servers():
    """Stop all running MCP servers."""
    names = list(_servers.keys())
    for name in names:
        await stop_server(name)


def get_server(name: str) -> Optional[MCPServer]:
    """Get a running MCP server by name."""
    server = _servers.get(name)
    if server and server.alive:
        return server
    return None


def get_all_servers() -> dict[str, MCPServer]:
    """Get all running MCP servers."""
    return {k: v for k, v in _servers.items() if v.alive}


# ─── Tool bridge ─────────────────────────────

def get_all_mcp_tools() -> list[dict]:
    """Get all tools from all running MCP servers, formatted for display."""
    all_tools = []
    for name, server in _servers.items():
        if not server.alive:
            continue
        for tool in server.tools:
            all_tools.append({
                "server": name,
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "input_schema": tool.get("inputSchema", {}),
            })
    return all_tools


def register_mcp_tools_to_registry():
    """Register all MCP tools into openlama's tool registry."""
    from openlama.tools.registry import register_tool

    for name, server in _servers.items():
        if not server.alive:
            continue
        for tool in server.tools:
            tool_name = tool.get("name", "")
            registry_name = f"mcp_{name}_{tool_name}"
            schema = tool.get("inputSchema", {"type": "object", "properties": {}})

            # Create async executor closure
            _server = server
            _tool_name = tool_name

            async def _execute(args: dict, s=_server, tn=_tool_name) -> str:
                return await s.call_tool(tn, args)

            register_tool(
                name=registry_name,
                description=f"[MCP:{name}] {tool.get('description', '')}",
                parameters=schema,
                execute=_execute,
            )

    logger.info("registered MCP tools to registry")
