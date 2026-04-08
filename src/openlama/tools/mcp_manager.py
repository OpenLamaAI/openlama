"""MCP manager tool — install, remove, list, restart MCP servers via chat."""
from __future__ import annotations

import json

from openlama.tools.registry import register_tool
from openlama.core.mcp_client import (
    add_server_config,
    remove_server_config,
    list_server_configs,
    start_server,
    stop_server,
    get_all_servers,
    get_all_mcp_tools,
    register_mcp_tools_to_registry,
)


async def _mcp_manager(args: dict) -> str:
    action = args.get("action", "list")

    if action == "list":
        configs = list_server_configs()
        running = get_all_servers()

        if not configs:
            return "No MCP servers configured. Use the 'install' action to add one."

        lines = ["📡 MCP Server List:"]
        for name, conf in configs.items():
            status = "🟢 Running" if name in running else "🔴 Stopped"
            cmd = conf.get("command", "?")
            cmd_args = " ".join(conf.get("args", []))
            lines.append(f"- **{name}** [{status}]: `{cmd} {cmd_args}`")

        return "\n".join(lines)

    if action == "install":
        name = args.get("server_name", "").strip()
        command = args.get("command", "").strip()
        if not name:
            return "Server name (server_name) is required."
        if not command:
            return "Command is required."

        cmd_args_raw = args.get("args", "")
        if isinstance(cmd_args_raw, str):
            try:
                cmd_args = json.loads(cmd_args_raw) if cmd_args_raw else []
            except json.JSONDecodeError:
                cmd_args = cmd_args_raw.split() if cmd_args_raw else []
        else:
            cmd_args = cmd_args_raw or []

        env_raw = args.get("env", "")
        env = None
        if env_raw:
            if isinstance(env_raw, str):
                try:
                    env = json.loads(env_raw)
                except json.JSONDecodeError:
                    env = None
            elif isinstance(env_raw, dict):
                env = env_raw

        add_server_config(name, command, cmd_args, env)

        # Try to start the server immediately
        ok = await start_server(name)
        if ok:
            register_mcp_tools_to_registry()
            return f"MCP server '{name}' has been installed and started."
        return f"MCP server '{name}' was added to configuration but failed to start. Please check the command."

    if action == "remove":
        name = args.get("server_name", "").strip()
        if not name:
            return "Server name (server_name) is required."

        await stop_server(name)
        if remove_server_config(name):
            return f"MCP server '{name}' has been removed."
        return f"MCP server '{name}' not found."

    if action == "status":
        running = get_all_servers()
        tools = get_all_mcp_tools()

        if not running:
            return "No MCP servers are running."

        lines = ["📡 MCP Server Status:"]
        for name, server in running.items():
            tool_count = len([t for t in tools if t["server"] == name])
            lines.append(f"- **{name}**: PID {server.process.pid if server.process else '?'}, {tool_count} tool(s)")

        if tools:
            lines.append("\n🔧 Available MCP Tools:")
            for t in tools:
                lines.append(f"- `mcp_{t['server']}_{t['name']}`: {t['description'][:60]}")

        return "\n".join(lines)

    if action == "restart":
        name = args.get("server_name", "").strip()
        if not name:
            return "Server name (server_name) is required."

        await stop_server(name)
        ok = await start_server(name)
        if ok:
            register_mcp_tools_to_registry()
            return f"MCP server '{name}' has been restarted."
        return f"Failed to restart MCP server '{name}'."

    if action == "tools":
        tools = get_all_mcp_tools()
        if not tools:
            return "No MCP tools available."

        lines = ["🔧 MCP Tool List:"]
        for t in tools:
            lines.append(f"- `mcp_{t['server']}_{t['name']}`: {t['description']}")
        return "\n".join(lines)

    return f"Unknown action: {action}. Available: install, list, remove, status, restart, tools"


register_tool(
    name="mcp_manager",
    description="Install, manage, and remove MCP (Model Context Protocol) servers. Integrates external tools and services.",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["install", "list", "remove", "status", "restart", "tools"],
                "description": "Action to perform",
            },
            "server_name": {
                "type": "string",
                "description": "MCP server name (e.g., github, filesystem)",
            },
            "command": {
                "type": "string",
                "description": "Server execution command (e.g., npx, python, node)",
            },
            "args": {
                "type": "string",
                "description": "Command arguments (JSON array or space-separated, e.g., [\"-y\", \"@github/github-mcp\"])",
            },
            "env": {
                "type": "string",
                "description": "Environment variables (JSON object, e.g., {\"GITHUB_TOKEN\": \"...\"})",
            },
        },
        "required": ["action"],
    },
    execute=_mcp_manager,
)
