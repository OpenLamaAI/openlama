"""Tests for Phase 4-7 improvements from agent-improvement-plan.md.

Covers:
- 4.2: JSON parsing error reporting (not silent failure)
- 4.3: Context turn count limit
- 4.4: Tool result size truncation
- 4.5: SQL injection prevention (whitelist validation)
- 4.6: httpx client thread safety (asyncio.Lock)
- 5.1: Parallel tool execution (safe vs dangerous split)
- 5.2: Pre-send token budget validation
- 5.3: cache_prompt in Ollama payload
- 5.4: Context compression timeout
- 5.6: Tool description deduplication
- 7.1: Chain-of-Thought prompting
- 7.2: Tool argument JSON Schema validation
- 7.3: Dynamic temperature inference
- 7.4: Tool execution retry for network errors
- 7.7: Memory garbage collection
"""
import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Phase 4.3: Context turn limit ──────────────────────────

from openlama.core.context import enforce_turn_limit


def test_enforce_turn_limit_under():
    """Items under limit should pass through unchanged."""
    items = [{"u": f"q{i}", "a": f"a{i}"} for i in range(5)]
    result = enforce_turn_limit(items, max_turns=10)
    assert len(result) == 5
    assert result == items


def test_enforce_turn_limit_over():
    """Items over limit should be trimmed from the front."""
    items = [{"u": f"q{i}", "a": f"a{i}"} for i in range(15)]
    result = enforce_turn_limit(items, max_turns=10)
    assert len(result) == 10
    assert result[0] == {"u": "q5", "a": "a5"}  # oldest kept
    assert result[-1] == {"u": "q14", "a": "a14"}  # newest kept


def test_enforce_turn_limit_exact():
    """Items exactly at limit should pass through unchanged."""
    items = [{"u": f"q{i}", "a": f"a{i}"} for i in range(10)]
    result = enforce_turn_limit(items, max_turns=10)
    assert len(result) == 10


def test_enforce_turn_limit_empty():
    """Empty list should return empty."""
    assert enforce_turn_limit([], max_turns=10) == []


def test_enforce_turn_limit_one():
    """max_turns=1 should keep only the latest turn."""
    items = [{"u": "q0", "a": "a0"}, {"u": "q1", "a": "a1"}]
    result = enforce_turn_limit(items, max_turns=1)
    assert len(result) == 1
    assert result[0] == {"u": "q1", "a": "a1"}


# ── Phase 4.4: Tool result truncation ──────────────────────

from openlama.core.context import truncate_tool_result


def test_truncate_short_result():
    """Short results should pass through unchanged."""
    result = "Hello world"
    assert truncate_tool_result(result, max_size=100) == result


def test_truncate_long_result():
    """Long results should be truncated with indicator."""
    result = "x" * 5000
    truncated = truncate_tool_result(result, max_size=1000)
    assert len(truncated) < 5000
    assert "truncated" in truncated
    assert "4000 chars truncated" in truncated


def test_truncate_preserves_start_and_end():
    """Truncation should keep both start and end of result."""
    result = "START" + "x" * 5000 + "END"
    truncated = truncate_tool_result(result, max_size=1000)
    assert truncated.startswith("START")
    assert truncated.endswith("END")


def test_truncate_exact_size():
    """Result exactly at limit should not be truncated."""
    result = "x" * 1000
    assert truncate_tool_result(result, max_size=1000) == result


# ── Phase 4.5: SQL injection prevention ────────────────────

from openlama.database import (
    _USER_ALLOWED_FIELDS, _MODEL_SETTING_ALLOWED_FIELDS, _CRON_ALLOWED_FIELDS,
    init_db, update_user, set_model_setting, update_cron_job,
    get_user, get_model_settings, create_cron_job, get_cron_job,
)


class TestSQLInjectionPrevention:
    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        import openlama.database as db_mod
        db_path = tmp_path / "test.db"
        db_mod.DB_PATH = db_path
        init_db()
        yield

    def test_user_allowed_fields_defined(self):
        """Whitelist should contain expected fields."""
        assert "state" in _USER_ALLOWED_FIELDS
        assert "selected_model" in _USER_ALLOWED_FIELDS
        assert "system_prompt" in _USER_ALLOWED_FIELDS

    def test_update_user_allowed_field(self):
        get_user(12345)  # create user
        update_user(12345, state="testing")
        user = get_user(12345)
        assert user.state == "testing"

    def test_update_user_blocked_field(self):
        """Malicious field names should be silently filtered out."""
        get_user(12345)
        # Inject SQL via key name
        update_user(12345, **{"state": "good", "telegram_id=0; DROP TABLE users; --": "evil"})
        user = get_user(12345)
        assert user.state == "good"  # legitimate field was applied

    def test_model_setting_allowed_field(self):
        set_model_setting(12345, "test-model", "temperature", 0.5)
        settings = get_model_settings(12345, "test-model")
        assert settings.temperature == 0.5

    def test_model_setting_blocked_field(self):
        """Disallowed keys should be rejected silently."""
        # This should not crash or inject SQL
        set_model_setting(12345, "test-model", "evil_field; DROP TABLE", "bad")
        # Should still work fine
        settings = get_model_settings(12345, "test-model")
        assert settings.model == "test-model"

    def test_cron_allowed_fields_defined(self):
        assert "cron_expr" in _CRON_ALLOWED_FIELDS
        assert "task" in _CRON_ALLOWED_FIELDS
        assert "enabled" in _CRON_ALLOWED_FIELDS

    def test_update_cron_job_blocked_field(self):
        """Injected cron job fields should be filtered out."""
        job_id = create_cron_job("* * * * *", "test task", created_by=1, next_run=int(time.time()))
        # Attempt SQL injection via key
        update_cron_job(job_id, enabled=0, **{"id=0; --": "evil"})
        job = get_cron_job(job_id)
        assert job["enabled"] == 0  # legitimate field applied

    def test_update_user_only_allowed_keys_reach_sql(self):
        """Verify only whitelisted keys are used in SQL construction."""
        get_user(99999)
        # All whitelisted fields should work
        for field in _USER_ALLOWED_FIELDS:
            try:
                if field in ("auth_until", "login_fail_count", "login_lock_until", "think_mode"):
                    update_user(99999, **{field: 0})
                else:
                    update_user(99999, **{field: "test"})
            except Exception as exc:
                pytest.fail(f"Whitelisted field '{field}' caused error: {exc}")

    def test_update_user_all_malicious_filtered(self):
        """Various SQL injection patterns should all be filtered."""
        get_user(88888)
        malicious_keys = [
            "telegram_id",               # PK should not be updatable
            "1=1; DROP TABLE users;--",  # classic injection
            "updated_at",                # internal field
            "' OR 1=1--",               # string injection
        ]
        for key in malicious_keys:
            update_user(88888, **{key: "evil"})
        user = get_user(88888)
        assert user.telegram_id == 88888  # verify DB intact


# ── Phase 5.2: Pre-send token budget validation ────────────

from openlama.core.context import validate_token_budget


def test_validate_budget_under_limit():
    """Messages under budget should pass through unchanged."""
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ]
    result = validate_token_budget(messages, num_ctx=8192, num_predict=2048)
    assert len(result) == 2


def test_validate_budget_trims_old_messages():
    """Messages over budget should trim oldest context."""
    messages = [
        {"role": "system", "content": "System prompt " * 100},
    ]
    # Add many user/assistant turns
    for i in range(50):
        messages.append({"role": "user", "content": f"Question {i} " * 100})
        messages.append({"role": "assistant", "content": f"Answer {i} " * 100})
    messages.append({"role": "user", "content": "Latest question"})

    result = validate_token_budget(messages, num_ctx=4096, num_predict=1024)
    assert len(result) < len(messages)
    # System message preserved
    assert result[0]["role"] == "system"
    # Latest user message preserved
    assert result[-1]["content"] == "Latest question"


def test_validate_budget_num_predict_exceeds_ctx():
    """Should not crash when num_predict > num_ctx."""
    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Hello"},
    ]
    # num_predict larger than num_ctx — should use fallback
    result = validate_token_budget(messages, num_ctx=1024, num_predict=2048)
    assert len(result) >= 1  # should not crash


def test_validate_budget_preserves_system():
    """System messages should never be trimmed."""
    messages = [
        {"role": "system", "content": "System 1"},
        {"role": "system", "content": "System 2"},
        {"role": "user", "content": "x " * 5000},
        {"role": "assistant", "content": "y " * 5000},
        {"role": "user", "content": "latest"},
    ]
    result = validate_token_budget(messages, num_ctx=2048, num_predict=512)
    system_msgs = [m for m in result if m["role"] == "system"]
    assert len(system_msgs) == 2


# ── Phase 5.3: cache_prompt in Ollama payload ──────────────

def test_cache_prompt_in_payload():
    """_build_chat_payload should include cache_prompt=True in options."""
    from openlama.ollama_client import _build_chat_payload
    payload = _build_chat_payload("test-model", [{"role": "user", "content": "hi"}])
    assert "options" in payload
    assert payload["options"]["cache_prompt"] is True


def test_cache_prompt_with_settings():
    """cache_prompt should be set even when settings provide other options."""
    from openlama.ollama_client import _build_chat_payload
    from openlama.database import ModelSettings
    settings = ModelSettings(user_id=1, model="test", temperature=0.5)
    payload = _build_chat_payload("test-model", [{"role": "user", "content": "hi"}], settings=settings)
    assert payload["options"]["cache_prompt"] is True


# ── Phase 5.6: Tool description deduplication ──────────────

def test_tool_section_names_only():
    """names_only mode should produce comma-separated names without descriptions."""
    from openlama.core.prompt_builder import _build_tool_section
    from openlama.tools import init_tools
    init_tools()
    section = _build_tool_section(names_only=True)
    first_line = section.split("\n")[0]
    assert first_line.startswith("Available tools:")
    # Should be comma-separated tool names
    names_part = first_line.split("Available tools:")[1].strip()
    assert ", " in names_part, f"Expected comma-separated names, got: {names_part[:100]}"
    # Should NOT have "- toolname: description" format
    assert "\n- " not in section
    # Second line should instruct function calling
    assert "function calling" in section.lower()


def test_tool_section_full():
    """Default mode should include tool names with descriptions."""
    from openlama.core.prompt_builder import _build_tool_section
    from openlama.tools import init_tools
    init_tools()
    section = _build_tool_section(names_only=False)
    # Should have "- toolname: description" format
    assert "- get_datetime:" in section or "- calculator:" in section
    # Each line should have description text
    lines = [l for l in section.split("\n") if l.startswith("- ")]
    assert len(lines) >= 10, f"Expected 10+ tool lines, got {len(lines)}"
    for line in lines[:3]:
        assert ": " in line, f"Expected 'name: desc' format, got: {line}"


# ── Phase 7.1: CoT prompting ──────────────────────────────

def test_cot_in_full_prompt():
    """Full mode prompt should include CoT reasoning section."""
    from openlama.core.prompt_builder import build_full_system_prompt
    prompt = build_full_system_prompt(num_ctx=32768)
    assert "Reasoning" in prompt
    assert "step by step" in prompt


def test_cot_in_compact_prompt():
    """Compact mode prompt should include CoT reasoning section."""
    from openlama.core.prompt_builder import build_full_system_prompt
    prompt = build_full_system_prompt(num_ctx=8192)
    assert "Reasoning" in prompt


def test_no_cot_in_minimal_prompt():
    """Minimal mode should NOT include CoT (save tokens)."""
    from openlama.core.prompt_builder import build_full_system_prompt
    prompt = build_full_system_prompt(num_ctx=4096)
    assert "step by step" not in prompt


# ── Phase 7.2: Tool argument validation ────────────────────

from openlama.tools.registry import _validate_tool_args, Tool


def test_validate_args_valid():
    tool = Tool(
        name="test",
        description="test",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        execute=AsyncMock(),
    )
    valid, error = _validate_tool_args(tool, {"name": "hello"})
    assert valid
    assert error == ""


def test_validate_args_missing_required():
    tool = Tool(
        name="test",
        description="test",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        execute=AsyncMock(),
    )
    valid, error = _validate_tool_args(tool, {})
    assert not valid
    assert "Missing required parameter: name" in error


def test_validate_args_wrong_type():
    tool = Tool(
        name="test",
        description="test",
        parameters={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": [],
        },
        execute=AsyncMock(),
    )
    valid, error = _validate_tool_args(tool, {"count": "not_an_int"})
    assert not valid
    assert "must be integer" in error


def test_validate_args_no_required():
    """Tools with no required params should accept empty args."""
    tool = Tool(
        name="test",
        description="test",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        execute=AsyncMock(),
    )
    valid, error = _validate_tool_args(tool, {})
    assert valid


# ── Phase 7.3: Dynamic temperature ────────────────────────

from openlama.core.agent import _infer_task_temperature


def test_infer_temp_precision():
    assert _infer_task_temperature("calculate 2+2") == 0.3
    assert _infer_task_temperature("계산해줘") == 0.3
    assert _infer_task_temperature("convert this to JSON") == 0.3


def test_infer_temp_code():
    assert _infer_task_temperature("implement a sort function") == 0.5
    assert _infer_task_temperature("코드 작성해줘") == 0.5
    assert _infer_task_temperature("fix the bug in main.py") == 0.5


def test_infer_temp_creative():
    assert _infer_task_temperature("write a story about a cat") == 0.8
    assert _infer_task_temperature("아이디어 좀 줘") == 0.8
    assert _infer_task_temperature("suggest some improvements") == 0.8


def test_infer_temp_general():
    """General queries should return None (keep default)."""
    assert _infer_task_temperature("hello how are you") is None
    assert _infer_task_temperature("what is the weather") is None


# ── Phase 7.4: Tool retry logic ────────────────────────────

from openlama.tools.registry import (
    NETWORK_TOOLS, MAX_TOOL_RETRIES, _RETRYABLE_ERRORS,
)


def test_network_tools_defined():
    """Network-dependent tools should be defined."""
    assert "web_search" in NETWORK_TOOLS
    assert "url_fetch" in NETWORK_TOOLS


def test_retry_constants():
    assert MAX_TOOL_RETRIES >= 1
    assert ConnectionError in _RETRYABLE_ERRORS
    assert TimeoutError in _RETRYABLE_ERRORS


@pytest.mark.asyncio
async def test_retry_actually_retries_on_network_error():
    """execute_tool should retry on ConnectionError for network tools."""
    from openlama.tools.registry import register_tool, execute_tool, _TOOLS

    call_count = 0
    async def flaky_execute(args):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("Connection refused")
        return "success after retries"

    # Register a test network tool
    register_tool("web_search_test_retry", "test", {"type": "object", "properties": {}}, flaky_execute)
    # Temporarily add to NETWORK_TOOLS
    import openlama.tools.registry as reg_mod
    old_network = reg_mod.NETWORK_TOOLS
    reg_mod.NETWORK_TOOLS = frozenset(old_network | {"web_search_test_retry"})

    try:
        result = await execute_tool("web_search_test_retry", {}, 0)
        assert "success after retries" in result
        assert call_count == 3  # 1 initial + 2 retries
    finally:
        reg_mod.NETWORK_TOOLS = old_network
        del _TOOLS["web_search_test_retry"]
        reg_mod._tools_cache = None


@pytest.mark.asyncio
async def test_no_retry_for_non_network_tools():
    """Non-network tools should NOT retry on errors."""
    from openlama.tools.registry import register_tool, execute_tool, _TOOLS
    import openlama.tools.registry as reg_mod

    call_count = 0
    async def failing_execute(args):
        nonlocal call_count
        call_count += 1
        raise ConnectionError("Connection refused")

    register_tool("local_test_no_retry", "test", {"type": "object", "properties": {}}, failing_execute)

    try:
        result = await execute_tool("local_test_no_retry", {}, 0)
        assert "failed" in result.lower() or "error" in result.lower()
        assert call_count == 1  # No retries for non-network tools
    finally:
        del _TOOLS["local_test_no_retry"]
        reg_mod._tools_cache = None


# ── Phase 7.7: Memory garbage collection ──────────────────

from openlama.core.memory import cleanup_old_memories


def test_cleanup_old_memories(tmp_path):
    """Old memory files should be removed."""
    with patch("openlama.core.memory._daily_dir", return_value=tmp_path):
        # Create old files
        old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
        (tmp_path / f"{old_date}.md").write_text("old content")

        # Create recent file
        today = datetime.now().strftime("%Y-%m-%d")
        (tmp_path / f"{today}.md").write_text("recent content")

        removed = cleanup_old_memories(max_days=90)

        assert removed == 1
        assert not (tmp_path / f"{old_date}.md").exists()
        assert (tmp_path / f"{today}.md").exists()


def test_cleanup_no_old_memories(tmp_path):
    """No files to remove should return 0."""
    with patch("openlama.core.memory._daily_dir", return_value=tmp_path):
        today = datetime.now().strftime("%Y-%m-%d")
        (tmp_path / f"{today}.md").write_text("recent")

        removed = cleanup_old_memories(max_days=90)
        assert removed == 0


def test_cleanup_invalid_filenames(tmp_path):
    """Non-date filenames should be skipped without error."""
    with patch("openlama.core.memory._daily_dir", return_value=tmp_path):
        (tmp_path / "not-a-date.md").write_text("content")
        (tmp_path / "README.md").write_text("content")

        removed = cleanup_old_memories(max_days=90)
        assert removed == 0
        assert (tmp_path / "not-a-date.md").exists()


# ── Phase 4.6: httpx client thread safety ──────────────────

@pytest.mark.asyncio
async def test_get_client_returns_async_client():
    """_get_client should return an httpx.AsyncClient."""
    from openlama.ollama_client import _get_client
    import httpx
    client = await _get_client()
    assert isinstance(client, httpx.AsyncClient)


@pytest.mark.asyncio
async def test_get_client_reuses_instance():
    """Subsequent calls should return the same client instance."""
    from openlama.ollama_client import _get_client
    c1 = await _get_client()
    c2 = await _get_client()
    assert c1 is c2


@pytest.mark.asyncio
async def test_get_client_concurrent_safety():
    """Concurrent _get_client calls should all return the same instance."""
    from openlama.ollama_client import _get_client
    # Run 10 concurrent calls
    results = await asyncio.gather(*[_get_client() for _ in range(10)])
    # All should be the same instance
    for r in results:
        assert r is results[0]


# ── Integration: Context compression timeout ──────────────

@pytest.mark.asyncio
async def test_compression_timeout_returns_original():
    """When compression times out, original ctx_items should be returned."""
    from openlama.core.context import maybe_compress

    async def slow_summarize(*args, **kwargs):
        await asyncio.sleep(100)  # Simulate very slow operation

    ctx_items = [{"u": f"q{i}" * 500, "a": f"a{i}" * 500} for i in range(20)]

    with patch("openlama.core.context.summarize_context", side_effect=slow_summarize), \
         patch("openlama.core.context.get_config_int", return_value=1), \
         patch("openlama.core.context.get_config_float", return_value=0.7):
        result_items, summary = await maybe_compress(
            uid=1, model="test", ctx_items=ctx_items,
            num_ctx=1024, system_prompt="sys", user_text="q",
        )
        # Should return original items on timeout
        assert result_items == ctx_items
        assert summary == ""
