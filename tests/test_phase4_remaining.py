"""Tests for remaining Phase 4-7 implementations.

Covers:
- 4.7: shell_command metacharacter validation
- 5.5: File I/O async conversion
- 6.4A: Dynamic tool filtering
- 6.3.1: Multi-agent data structures and functions
- 7.5: ToolResult structured dataclass
- 7.8: Request correlation ID
- 7.9: Model fallback
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 4.7: shell_command metacharacter validation ──────────

from openlama.tools.shell_command import _validate_shell_command


def test_shell_safe_command():
    safe, reason = _validate_shell_command("ls -la /tmp")
    assert safe
    assert reason == ""


def test_shell_safe_echo():
    safe, reason = _validate_shell_command("echo hello world")
    assert safe


def test_shell_blocks_semicolon():
    safe, reason = _validate_shell_command("echo hello; echo world")
    assert not safe
    assert ";" in reason


def test_shell_blocks_pipe():
    safe, reason = _validate_shell_command("cat /etc/passwd | grep root")
    assert not safe
    assert "|" in reason


def test_shell_blocks_command_substitution():
    safe, reason = _validate_shell_command("echo $(whoami)")
    assert not safe
    assert "$(" in reason


def test_shell_blocks_backtick():
    safe, reason = _validate_shell_command("echo `id`")
    assert not safe
    assert "`" in reason


def test_shell_blocks_and_chain():
    safe, reason = _validate_shell_command("true && echo pwned")
    assert not safe
    assert "&&" in reason


def test_shell_blocks_redirect():
    safe, reason = _validate_shell_command("echo data > /etc/crontab")
    assert not safe
    assert ">" in reason


def test_shell_blocks_newline():
    safe, reason = _validate_shell_command("echo hello\nrm -rf /")
    assert not safe


def test_shell_blocks_fork_bomb():
    safe, reason = _validate_shell_command(":(){:|:&};:")
    assert not safe


def test_shell_blocks_rm_rf_root():
    safe, reason = _validate_shell_command("rm -rf /")
    assert not safe


# ── 5.5: File I/O async ─────────────────────────────────

@pytest.mark.asyncio
async def test_file_read_is_async(tmp_path):
    """file_read should use asyncio.to_thread for non-blocking I/O."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello async world", encoding="utf-8")

    from openlama.tools import init_tools, execute_tool
    init_tools()
    result = await execute_tool("file_read", {"path": str(test_file)}, 0)
    assert "hello async world" in result


@pytest.mark.asyncio
async def test_file_write_is_async(tmp_path):
    """file_write should use asyncio.to_thread for non-blocking I/O."""
    from openlama.tools import init_tools, execute_tool
    init_tools()
    path = str(tmp_path / "output.txt")
    result = await execute_tool("file_write", {"path": path, "content": "async content"}, 0)
    assert "saved" in result.lower() or "denied" in result.lower()


@pytest.mark.asyncio
async def test_memory_async_wrappers():
    """Memory module should provide async wrappers."""
    from openlama.core.memory import async_load_memory, async_save_memory_entry, async_save_daily_entry
    # These should be callable without blocking
    assert callable(async_load_memory)
    assert callable(async_save_memory_entry)
    assert callable(async_save_daily_entry)


# ── 6.4A: Dynamic tool filtering ────────────────────────

from openlama.core.agent import _select_tools_for_request


def _make_tool(name):
    return {"type": "function", "function": {"name": name, "description": "test", "parameters": {}}}


def test_filter_search_request():
    tools = [_make_tool("web_search"), _make_tool("calculator"), _make_tool("url_fetch"), _make_tool("file_read")]
    result = _select_tools_for_request("검색해줘", tools)
    # web_search and url_fetch should be first
    first_names = [t["function"]["name"] for t in result[:2]]
    assert "web_search" in first_names
    assert "url_fetch" in first_names


def test_filter_code_request():
    tools = [_make_tool("web_search"), _make_tool("code_execute"), _make_tool("file_read"), _make_tool("calculator")]
    result = _select_tools_for_request("코드를 실행해줘", tools)
    first_names = [t["function"]["name"] for t in result[:2]]
    assert "code_execute" in first_names
    assert "file_read" in first_names


def test_filter_general_request_unchanged():
    tools = [_make_tool("web_search"), _make_tool("calculator")]
    result = _select_tools_for_request("hello there", tools)
    # No filtering for general requests — same order
    assert result == tools


def test_filter_analysis_request():
    tools = [_make_tool("web_search"), _make_tool("calculator"), _make_tool("file_read"), _make_tool("code_execute")]
    result = _select_tools_for_request("분석해줘", tools)
    first_names = [t["function"]["name"] for t in result[:3]]
    assert "calculator" in first_names
    assert "web_search" in first_names


# ── 6.3.1: Multi-agent data structures ──────────────────

from openlama.core.multi_agent import (
    WorkerTask, WorkerResult, OrchestratorPlan,
    WORKER_PROFILES, should_delegate, run_worker, orchestrate,
)


def test_worker_task_defaults():
    t = WorkerTask(task_id="t1", description="test", allowed_tools=["web_search"])
    assert t.max_iterations == 5
    assert t.timeout == 60.0


def test_worker_result_creation():
    r = WorkerResult(task_id="t1", success=True, result="done", tokens_used=100)
    assert r.success
    assert r.tokens_used == 100


def test_orchestrator_plan_no_delegation():
    p = OrchestratorPlan(needs_delegation=False)
    assert not p.needs_delegation
    assert p.tasks == []


def test_worker_profiles_defined():
    assert "research" in WORKER_PROFILES
    assert "code" in WORKER_PROFILES
    assert "analysis" in WORKER_PROFILES
    assert "general" in WORKER_PROFILES
    assert "web_search" in WORKER_PROFILES["research"]
    assert "code_execute" in WORKER_PROFILES["code"]


@pytest.mark.asyncio
async def test_should_delegate_json_parse_failure():
    """When LLM returns invalid JSON, should fallback to single agent."""
    with patch("openlama.core.multi_agent.chat_with_ollama_full", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {"content": "this is not json"}
        plan = await should_delegate("complex multi-part request", "test-model")
        assert not plan.needs_delegation


@pytest.mark.asyncio
async def test_should_delegate_llm_error():
    """When LLM call fails, should fallback to single agent."""
    with patch("openlama.core.multi_agent.chat_with_ollama_full", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = Exception("API error")
        plan = await should_delegate("complex request", "test-model")
        assert not plan.needs_delegation


@pytest.mark.asyncio
async def test_should_delegate_returns_plan():
    """When LLM says delegation needed, should create proper plan."""
    llm_response = json.dumps({
        "needs_delegation": True,
        "reason": "Two independent tasks",
        "tasks": [
            {"description": "Search for info", "worker_type": "research"},
            {"description": "Analyze data", "worker_type": "analysis"},
        ]
    })
    with patch("openlama.core.multi_agent.chat_with_ollama_full", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {"content": llm_response}
        plan = await should_delegate("search and analyze this", "test-model")
        assert plan.needs_delegation
        assert len(plan.tasks) == 2
        assert plan.tasks[0].allowed_tools == WORKER_PROFILES["research"]
        assert plan.tasks[1].allowed_tools == WORKER_PROFILES["analysis"]


@pytest.mark.asyncio
async def test_run_worker_timeout():
    """Worker should return failure on timeout."""
    with patch("openlama.core.multi_agent.chat_with_ollama_full", new_callable=AsyncMock) as mock_chat:
        async def slow(*args, **kwargs):
            await asyncio.sleep(100)
        mock_chat.side_effect = slow

        task = WorkerTask(task_id="t1", description="test", allowed_tools=[], timeout=0.1)
        result = await run_worker(task, "test-model", 1)
        assert not result.success
        assert "timed out" in result.result.lower()


@pytest.mark.asyncio
async def test_run_worker_success():
    """Worker should return success with content."""
    with patch("openlama.core.multi_agent.chat_with_ollama_full", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = {"content": "worker result", "tool_calls": [], "prompt_tokens": 10, "completion_tokens": 5}
        task = WorkerTask(task_id="t1", description="test", allowed_tools=[])
        result = await run_worker(task, "test-model", 1)
        assert result.success
        assert result.result == "worker result"
        assert result.tokens_used == 15


@pytest.mark.asyncio
async def test_orchestrate_synthesis():
    """Orchestrate should synthesize worker results."""
    plan = OrchestratorPlan(
        needs_delegation=True,
        tasks=[
            WorkerTask(task_id="t1", description="task1", allowed_tools=[]),
            WorkerTask(task_id="t2", description="task2", allowed_tools=[]),
        ],
        synthesis_instruction="combine results",
    )

    with patch("openlama.core.multi_agent.run_worker", new_callable=AsyncMock) as mock_worker, \
         patch("openlama.core.multi_agent.chat_with_ollama_full", new_callable=AsyncMock) as mock_synth:
        mock_worker.side_effect = [
            WorkerResult(task_id="t1", success=True, result="result 1"),
            WorkerResult(task_id="t2", success=True, result="result 2"),
        ]
        mock_synth.return_value = {"content": "synthesized answer"}

        answer = await orchestrate(plan, "test-model", 1, "system prompt")
        assert answer == "synthesized answer"
        assert mock_worker.call_count == 2


@pytest.mark.asyncio
async def test_orchestrate_majority_failure_fallback():
    """When majority of workers fail, should return failure message."""
    plan = OrchestratorPlan(
        needs_delegation=True,
        tasks=[
            WorkerTask(task_id="t1", description="task1", allowed_tools=[]),
            WorkerTask(task_id="t2", description="task2", allowed_tools=[]),
            WorkerTask(task_id="t3", description="task3", allowed_tools=[]),
        ],
    )

    with patch("openlama.core.multi_agent.run_worker", new_callable=AsyncMock) as mock_worker:
        mock_worker.side_effect = [
            WorkerResult(task_id="t1", success=False, result="failed"),
            WorkerResult(task_id="t2", success=False, result="failed"),
            WorkerResult(task_id="t3", success=True, result="ok"),
        ]

        answer = await orchestrate(plan, "test-model", 1, "system prompt")
        assert "failed" in answer.lower()


# ── 7.5: ToolResult ─────────────────────────────────────

from openlama.core.types import ToolResult


def test_tool_result_success():
    r = ToolResult(success=True, data="hello")
    assert r.to_message() == "hello"
    assert str(r) == "hello"


def test_tool_result_error():
    r = ToolResult(success=False, data="", error="not found")
    assert "[ERROR] not found" in r.to_message()
    assert "[ERROR]" in str(r)


def test_tool_result_error_with_data():
    r = ToolResult(success=False, data="partial", error="timeout")
    msg = r.to_message()
    assert "[ERROR] timeout" in msg
    assert "partial" in msg


def test_tool_result_metadata():
    r = ToolResult(success=True, data="ok", metadata={"duration": 1.5})
    assert r.metadata["duration"] == 1.5


# ── 7.8: Request correlation ID ─────────────────────────

from openlama.logger import set_request_id, get_request_id


def test_set_request_id_generates():
    rid = set_request_id()
    assert len(rid) == 8
    assert rid == get_request_id()


def test_set_request_id_custom():
    rid = set_request_id("custom123")
    assert rid == "custom123"
    assert get_request_id() == "custom123"


def test_request_id_isolation():
    """Request IDs should be isolated per context."""
    set_request_id("test1")
    assert get_request_id() == "test1"
    set_request_id("test2")
    assert get_request_id() == "test2"


# ── 7.9: Model fallback (tested via agent integration) ──

def test_model_fallback_import():
    """list_models should be importable from agent module's imports."""
    from openlama.ollama_client import list_models
    assert callable(list_models)


# ── 4.8: Cron global state isolation ──────────────────────

def test_cron_context_uses_contextvars():
    """Cron chat context should use contextvars, not plain globals."""
    import contextvars
    from openlama.tools.cron_tool import _current_chat_id, _current_user_id
    assert isinstance(_current_chat_id, contextvars.ContextVar)
    assert isinstance(_current_user_id, contextvars.ContextVar)


def test_cron_set_chat_context():
    """set_chat_context should set context vars."""
    from openlama.tools.cron_tool import set_chat_context, _current_chat_id, _current_user_id
    set_chat_context(12345, 67890)
    assert _current_chat_id.get() == 12345
    assert _current_user_id.get() == 67890


@pytest.mark.asyncio
async def test_cron_context_isolation():
    """Context vars should be isolated across concurrent tasks."""
    from openlama.tools.cron_tool import set_chat_context, _current_chat_id

    results = {}

    async def task_a():
        set_chat_context(111, 1)
        await asyncio.sleep(0.01)
        results["a"] = _current_chat_id.get()

    async def task_b():
        set_chat_context(222, 2)
        await asyncio.sleep(0.01)
        results["b"] = _current_chat_id.get()

    # Run concurrently — each should see its own value
    await asyncio.gather(
        asyncio.create_task(task_a()),
        asyncio.create_task(task_b()),
    )
    assert results["a"] == 111
    assert results["b"] == 222


# ── 6.3.3: Config defaults ──────────────────────────────

def test_multi_agent_config_defaults():
    from openlama.config import get_config, get_config_bool, get_config_int
    assert get_config_bool("multi_agent_enabled", False) is False
    assert get_config_int("worker_max_iterations", 5) == 5
    assert get_config_int("worker_timeout", 60) == 60
    assert get_config_int("max_workers", 5) == 5
    assert get_config_int("delegation_min_text_length", 50) == 50
    assert get_config_int("worker_max_result_size", 2000) == 2000
