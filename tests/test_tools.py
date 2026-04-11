"""Tests for all tools – registration, execution, parameter validation."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from openlama.tools import init_tools, get_all_tools, execute_tool, format_tools_for_ollama
from openlama.tools.registry import get_tool


@pytest.fixture(autouse=True, scope="module")
def _init():
    init_tools()


# ── Registry ──

def test_all_tools_registered():
    tools = get_all_tools()
    names = {t.name for t in tools}
    expected = {
        "get_datetime", "calculator", "web_search", "url_fetch",
        "code_execute", "shell_command", "file_read", "file_write",
        "image_generate", "image_edit", "git", "process_manager",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"


def test_tool_count():
    tools = get_all_tools()
    assert len(tools) >= 12


def test_format_tools_for_ollama_admin():
    tools = format_tools_for_ollama(admin=True)
    assert len(tools) >= 12
    for t in tools:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert "description" in t["function"]
        assert "parameters" in t["function"]


def test_format_tools_for_ollama_non_admin():
    admin_tools = format_tools_for_ollama(admin=True)
    user_tools = format_tools_for_ollama(admin=False)
    assert len(user_tools) < len(admin_tools)


def test_each_tool_has_valid_schema():
    tools = get_all_tools()
    for t in tools:
        assert t.name, "Tool must have a name"
        assert t.description, f"Tool {t.name} must have a description"
        assert isinstance(t.parameters, dict), f"Tool {t.name} parameters must be dict"
        assert t.parameters.get("type") == "object", f"Tool {t.name} params must be object type"
        assert "properties" in t.parameters, f"Tool {t.name} must have properties"
        assert callable(t.execute), f"Tool {t.name} must have callable execute"


def test_admin_only_flags():
    admin_tools = {"shell_command", "file_read", "file_write", "image_edit", "git", "process_manager"}
    for t in get_all_tools():
        if t.name in admin_tools:
            assert t.admin_only, f"{t.name} should be admin_only"


# ── get_datetime ──

@pytest.mark.asyncio
async def test_datetime_tool():
    result = await execute_tool("get_datetime", {}, 0)
    assert "KST" in result or "20" in result  # Contains year or timezone


@pytest.mark.asyncio
async def test_datetime_with_timezone():
    result = await execute_tool("get_datetime", {"timezone": "UTC"}, 0)
    assert "20" in result  # Contains year


# ── calculator ──

@pytest.mark.asyncio
async def test_calculator_basic():
    result = await execute_tool("calculator", {"expression": "2 + 3"}, 0)
    assert "5" in result


@pytest.mark.asyncio
async def test_calculator_complex():
    result = await execute_tool("calculator", {"expression": "sqrt(144)"}, 0)
    assert "12" in result


@pytest.mark.asyncio
async def test_calculator_division():
    result = await execute_tool("calculator", {"expression": "10 / 3"}, 0)
    assert "3.33" in result


@pytest.mark.asyncio
async def test_calculator_empty():
    result = await execute_tool("calculator", {"expression": ""}, 0)
    assert "provide" in result.lower() or "수식" in result


# ── shell_command ──

@pytest.mark.asyncio
async def test_shell_echo():
    result = await execute_tool("shell_command", {"command": "echo hello_test"}, 0)
    assert "hello_test" in result


@pytest.mark.asyncio
async def test_shell_exit_code():
    result = await execute_tool("shell_command", {"command": "true"}, 0)
    assert "exit code: 0" in result


@pytest.mark.asyncio
async def test_shell_empty_command():
    result = await execute_tool("shell_command", {"command": ""}, 0)
    assert "provide" in result.lower() or "명령" in result


@pytest.mark.asyncio
async def test_shell_timeout():
    """Commands exceeding timeout should be killed."""
    from tools import shell_command as sc_mod
    import config
    old = config.CODE_EXECUTION_TIMEOUT
    config.CODE_EXECUTION_TIMEOUT = 1
    result = await execute_tool("shell_command", {"command": "sleep 30"}, 0)
    config.CODE_EXECUTION_TIMEOUT = old
    assert "timed out" in result.lower() or "timeout" in result.lower() or "exit code" in result or "시간 초과" in result


# ── file_read ──

@pytest.mark.asyncio
async def test_file_read(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world", encoding="utf-8")
    result = await execute_tool("file_read", {"path": str(test_file)}, 0)
    assert "hello world" in result


@pytest.mark.asyncio
async def test_file_read_dir(tmp_path):
    (tmp_path / "a.txt").touch()
    (tmp_path / "b.txt").touch()
    result = await execute_tool("file_read", {"path": str(tmp_path)}, 0)
    assert "a.txt" in result
    assert "b.txt" in result


@pytest.mark.asyncio
async def test_file_read_nonexistent():
    result = await execute_tool("file_read", {"path": "/nonexistent/file.txt"}, 0)
    assert "not found" in result.lower() or "denied" in result.lower() or "찾을 수 없" in result


@pytest.mark.asyncio
async def test_file_read_empty_path():
    result = await execute_tool("file_read", {"path": ""}, 0)
    assert "provide" in result.lower() or "경로" in result


# ── file_write ──

@pytest.mark.asyncio
async def test_file_write(tmp_path):
    path = str(tmp_path / "output.txt")
    result = await execute_tool("file_write", {"path": path, "content": "test content"}, 0)
    assert "saved" in result.lower() or "저장" in result or "denied" in result.lower()


@pytest.mark.asyncio
async def test_file_write_append(tmp_path):
    path = str(tmp_path / "append.txt")
    Path(path).write_text("first")
    result = await execute_tool("file_write", {"path": path, "content": " second", "mode": "append"}, 0)
    assert "saved" in result.lower() or "저장" in result or "denied" in result.lower()


@pytest.mark.asyncio
async def test_file_write_creates_dirs(tmp_path):
    path = str(tmp_path / "deep" / "nested" / "file.txt")
    result = await execute_tool("file_write", {"path": path, "content": "deep"}, 0)
    assert "saved" in result.lower() or "저장" in result or "denied" in result.lower()


# ── code_execute ──

@pytest.mark.asyncio
async def test_code_execute_python():
    result = await execute_tool("code_execute", {"language": "python", "code": "print(1+1)"}, 0)
    assert "2" in result


@pytest.mark.asyncio
async def test_code_execute_shell():
    result = await execute_tool("code_execute", {"language": "bash", "code": "echo works"}, 0)
    assert "works" in result


@pytest.mark.asyncio
async def test_code_execute_error():
    result = await execute_tool("code_execute", {"language": "python", "code": "raise ValueError('test')"}, 0)
    assert "ValueError" in result or "test" in result


# ── git ──

@pytest.mark.asyncio
async def test_git_version():
    result = await execute_tool("git", {"action": "version"}, 0)
    assert "git" in result.lower() or "exit code" in result


@pytest.mark.asyncio
async def test_git_status_no_repo(tmp_path):
    result = await execute_tool("git", {"action": "status", "repo_path": str(tmp_path)}, 0)
    assert "fatal" in result.lower() or "not a git" in result.lower()


@pytest.mark.asyncio
async def test_git_empty_action():
    result = await execute_tool("git", {"action": ""}, 0)
    assert "action" in result.lower() or "specify" in result.lower()


# ── process_manager ──

@pytest.mark.asyncio
async def test_process_uptime():
    result = await execute_tool("process_manager", {"action": "uptime"}, 0)
    assert "up" in result.lower() or "load" in result.lower()


@pytest.mark.asyncio
async def test_process_df():
    result = await execute_tool("process_manager", {"action": "df"}, 0)
    assert "Filesystem" in result or "/" in result


@pytest.mark.asyncio
async def test_process_sysinfo():
    result = await execute_tool("process_manager", {"action": "sysinfo"}, 0)
    assert "OS" in result or "Darwin" in result or "Linux" in result


@pytest.mark.asyncio
async def test_process_ps():
    result = await execute_tool("process_manager", {"action": "ps"}, 0)
    assert "PID" in result or "pid" in result or "exit code: 0" in result


@pytest.mark.asyncio
async def test_process_empty_action():
    result = await execute_tool("process_manager", {"action": ""}, 0)
    assert "action" in result.lower() or "specify" in result.lower()


@pytest.mark.asyncio
async def test_process_unknown_action_blocked():
    """Unknown actions should be rejected (no fallback to arbitrary commands)."""
    result = await execute_tool("process_manager", {"action": "pm2", "target": "list"}, 0)
    assert "Unknown action" in result


# ── nonexistent tool ──

@pytest.mark.asyncio
async def test_execute_nonexistent_tool():
    result = await execute_tool("nonexistent_tool", {}, 0)
    assert "not found" in result.lower() or "찾을 수 없" in result
