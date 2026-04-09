"""Tests for daemon process detection — PID file + OS process scan."""

import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from openlama.daemon import (
    _read_pid,
    _find_running_process,
    get_daemon_status,
    PID_FILE,
)


# ── _read_pid ──

def test_read_pid_no_file(tmp_path):
    """No PID file → None."""
    with patch("openlama.daemon.PID_FILE", tmp_path / "nonexistent.pid"):
        assert _read_pid() is None


def test_read_pid_valid(tmp_path):
    """PID file with current process PID → returns PID."""
    pid_file = tmp_path / "openlama.pid"
    pid_file.write_text(str(os.getpid()))
    with patch("openlama.daemon.PID_FILE", pid_file):
        assert _read_pid() == os.getpid()


def test_read_pid_stale(tmp_path):
    """PID file with dead process → None + file removed."""
    pid_file = tmp_path / "openlama.pid"
    pid_file.write_text("99999999")  # very unlikely to be a real process
    with patch("openlama.daemon.PID_FILE", pid_file):
        assert _read_pid() is None
        assert not pid_file.exists()


def test_read_pid_invalid_content(tmp_path):
    """PID file with garbage → None + file removed."""
    pid_file = tmp_path / "openlama.pid"
    pid_file.write_text("not_a_number")
    with patch("openlama.daemon.PID_FILE", pid_file):
        assert _read_pid() is None
        assert not pid_file.exists()


# ── _find_running_process ──

def test_find_running_process_returns_int_or_none():
    """Should return int PID or None, never crash."""
    result = _find_running_process()
    assert result is None or isinstance(result, int)


def test_find_running_process_excludes_self():
    """Should not return our own PID."""
    result = _find_running_process()
    if result is not None:
        assert result != os.getpid()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test")
def test_find_running_process_parses_ps_output():
    """Mock ps output to verify parsing logic."""
    fake_ps = (
        "  PID COMMAND\n"
        "12345 /usr/bin/python3 /path/to/openlama start\n"
        "12346 /usr/bin/python3 /path/to/openlama status\n"
        "12347 grep openlama\n"
    )
    mock_result = MagicMock()
    mock_result.stdout = fake_ps
    mock_result.returncode = 0

    with patch("openlama.daemon.subprocess.run", return_value=mock_result):
        with patch("openlama.daemon.os.getpid", return_value=99999):
            pid = _find_running_process()
            assert pid == 12345  # only "openlama start" line


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test")
def test_find_running_process_excludes_management_commands():
    """Should not match --install-service, status, stop, doctor."""
    fake_ps = (
        "  PID COMMAND\n"
        "11111 python3 -m openlama.cli start --install-service\n"
        "22222 python3 -m openlama.cli status\n"
        "33333 python3 -m openlama.cli stop\n"
        "44444 python3 -m openlama.cli doctor\n"
    )
    mock_result = MagicMock()
    mock_result.stdout = fake_ps
    mock_result.returncode = 0

    with patch("openlama.daemon.subprocess.run", return_value=mock_result):
        with patch("openlama.daemon.os.getpid", return_value=99999):
            pid = _find_running_process()
            assert pid is None


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test")
def test_find_running_process_matches_cli_module():
    """Should match both 'openlama start' and 'openlama.cli start'."""
    fake_ps = (
        "  PID COMMAND\n"
        "55555 /usr/bin/python3 -m openlama.cli start\n"
    )
    mock_result = MagicMock()
    mock_result.stdout = fake_ps
    mock_result.returncode = 0

    with patch("openlama.daemon.subprocess.run", return_value=mock_result):
        with patch("openlama.daemon.os.getpid", return_value=99999):
            pid = _find_running_process()
            assert pid == 55555


def test_find_running_process_handles_subprocess_error():
    """Should return None if ps/tasklist fails."""
    with patch("openlama.daemon.subprocess.run", side_effect=Exception("fail")):
        assert _find_running_process() is None


def test_find_running_process_handles_timeout():
    """Should return None if ps/tasklist times out."""
    with patch("openlama.daemon.subprocess.run", side_effect=subprocess.TimeoutExpired("ps", 5)):
        assert _find_running_process() is None


# ── get_daemon_status ──

def test_status_from_pid_file(tmp_path):
    """PID file exists with live process → '🟢 Running (PID ...)'."""
    pid_file = tmp_path / "openlama.pid"
    pid_file.write_text(str(os.getpid()))
    with patch("openlama.daemon.PID_FILE", pid_file):
        status = get_daemon_status()
        assert "Running" in status
        assert str(os.getpid()) in status
        assert "service" not in status


def test_status_from_process_scan(tmp_path):
    """No PID file but process found via scan → '🟢 Running (PID ..., service)'."""
    pid_file = tmp_path / "nonexistent.pid"
    with patch("openlama.daemon.PID_FILE", pid_file):
        with patch("openlama.daemon._find_running_process", return_value=12345):
            status = get_daemon_status()
            assert "Running" in status
            assert "12345" in status
            assert "service" in status


def test_status_not_running(tmp_path):
    """No PID file, no process found → 'Not running'."""
    pid_file = tmp_path / "nonexistent.pid"
    with patch("openlama.daemon.PID_FILE", pid_file):
        with patch("openlama.daemon._find_running_process", return_value=None):
            status = get_daemon_status()
            assert "Not running" in status
