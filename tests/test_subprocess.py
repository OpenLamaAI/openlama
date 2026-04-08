"""Tests for src/openlama/utils/subprocess.py — async command runner."""

import pytest

from openlama.utils.subprocess import run_command


@pytest.mark.asyncio
async def test_run_command_simple_echo():
    result = await run_command("echo hello", shell=True)
    assert "hello" in result
    assert "[exit code: 0]" in result


@pytest.mark.asyncio
async def test_run_command_list_form():
    result = await run_command(["echo", "world"])
    assert "world" in result
    assert "[exit code: 0]" in result


@pytest.mark.asyncio
async def test_run_command_nonzero_exit():
    result = await run_command("exit 42", shell=True)
    assert "[exit code: 42]" in result


@pytest.mark.asyncio
async def test_run_command_stderr():
    result = await run_command("echo error >&2", shell=True)
    assert "[stderr]" in result
    assert "error" in result


@pytest.mark.asyncio
async def test_run_command_timeout():
    result = await run_command("sleep 60", shell=True, timeout=1)
    assert "timed out" in result.lower()


@pytest.mark.asyncio
async def test_run_command_stdout_and_stderr():
    result = await run_command("echo out && echo err >&2", shell=True)
    assert "out" in result
    assert "err" in result


@pytest.mark.asyncio
async def test_run_command_cwd(tmp_path):
    result = await run_command("pwd", shell=True, cwd=str(tmp_path))
    assert str(tmp_path) in result


@pytest.mark.asyncio
async def test_run_command_max_stdout_truncation():
    """Output should be truncated to max_stdout."""
    result = await run_command("python3 -c \"print('x' * 50000)\"", shell=True, max_stdout=100)
    # The output content (excluding [exit code: ...]) should be at most 100 chars
    lines = result.split("\n")
    first_line = lines[0]
    assert len(first_line) <= 100
