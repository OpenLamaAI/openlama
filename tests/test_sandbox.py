"""Tests for src/openlama/utils/sandbox.py — path sandboxing."""

from pathlib import Path

from openlama.utils.sandbox import is_safe_path


def test_is_safe_path_under_sandbox(monkeypatch):
    monkeypatch.setattr("openlama.utils.sandbox.get_config_bool", lambda k, d=False: True)
    monkeypatch.setattr("openlama.utils.sandbox.get_config", lambda k: "/allowed/sandbox")
    # Path under sandbox should be allowed
    assert is_safe_path("/allowed/sandbox/file.txt") is True


def test_is_safe_path_under_home(monkeypatch):
    monkeypatch.setattr("openlama.utils.sandbox.get_config_bool", lambda k, d=False: True)
    monkeypatch.setattr("openlama.utils.sandbox.get_config", lambda k: "/nonexistent/sandbox")
    home = str(Path.home())
    # Path under home should be allowed
    assert is_safe_path(home + "/Documents/file.txt") is True


def test_is_safe_path_blocks_outside(monkeypatch):
    monkeypatch.setattr("openlama.utils.sandbox.get_config_bool", lambda k, d=False: True)
    monkeypatch.setattr("openlama.utils.sandbox.get_config", lambda k: "/allowed/sandbox")
    # /etc is outside both sandbox and home
    assert is_safe_path("/etc/passwd") is False


def test_is_safe_path_sandbox_disabled(monkeypatch):
    monkeypatch.setattr("openlama.utils.sandbox.get_config_bool", lambda k, d=False: False)
    # When sandbox is disabled, everything is allowed
    assert is_safe_path("/etc/passwd") is True
    assert is_safe_path("/any/random/path") is True


def test_is_safe_path_traversal_blocked(monkeypatch):
    monkeypatch.setattr("openlama.utils.sandbox.get_config_bool", lambda k, d=False: True)
    monkeypatch.setattr("openlama.utils.sandbox.get_config", lambda k: "/allowed/sandbox")
    # Path traversal attempt
    assert is_safe_path("/allowed/sandbox/../../etc/passwd") is False
