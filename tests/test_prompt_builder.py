"""Tests for src/openlama/core/prompt_builder.py — system prompt generation and assembly."""

from pathlib import Path

import pytest

from openlama.core.prompt_builder import (
    build_full_system_prompt,
    generate_system_prompt,
    is_profile_setup_done,
    save_prompt_file,
)


@pytest.fixture
def prompts_dir(tmp_path, monkeypatch):
    """Set up a temp prompts directory and patch config."""
    d = tmp_path / "prompts"
    d.mkdir()
    monkeypatch.setattr("openlama.core.prompt_builder._prompts_dir", lambda: d)
    return d


# ── generate_system_prompt ──


def test_generate_system_prompt_returns_string(prompts_dir):
    result = generate_system_prompt()
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_system_prompt_has_tools_section(prompts_dir):
    result = generate_system_prompt()
    assert "## Tools" in result


def test_generate_system_prompt_has_system_header(prompts_dir):
    result = generate_system_prompt()
    assert "# System Prompt" in result


def test_generate_system_prompt_has_tool_triggers(prompts_dir):
    result = generate_system_prompt()
    assert "## Tool Triggers" in result


# ── build_full_system_prompt ──


def test_build_full_system_prompt_basic(prompts_dir):
    result = build_full_system_prompt()
    assert isinstance(result, str)
    assert "# System Prompt" in result


def test_build_full_system_prompt_includes_soul(prompts_dir):
    (prompts_dir / "SOUL.md").write_text("# Soul\nI am a helpful assistant with personality.", encoding="utf-8")
    result = build_full_system_prompt()
    assert "helpful assistant with personality" in result


def test_build_full_system_prompt_includes_users(prompts_dir):
    (prompts_dir / "USERS.md").write_text("# Users\nThe user prefers concise answers.", encoding="utf-8")
    result = build_full_system_prompt()
    assert "concise answers" in result


def test_build_full_system_prompt_excludes_memory(prompts_dir):
    """MEMORY.md should NOT be loaded into the system prompt (accessed via tool only)."""
    (prompts_dir / "MEMORY.md").write_text("# Memory\nUser likes coffee.", encoding="utf-8")
    result = build_full_system_prompt()
    assert "User likes coffee" not in result
    # But the memory section should be present
    assert "## Memory" in result


def test_build_full_system_prompt_assembles_all_parts(prompts_dir):
    (prompts_dir / "SOUL.md").write_text("# Soul\nI am uniquely creative.", encoding="utf-8")
    (prompts_dir / "USERS.md").write_text("# Users\nUser is a developer.", encoding="utf-8")
    (prompts_dir / "MEMORY.md").write_text("# Memory\nFavorite color is blue.", encoding="utf-8")
    result = build_full_system_prompt()
    assert "uniquely creative" in result
    assert "User is a developer" in result
    # MEMORY.md content should NOT be in prompt
    assert "Favorite color is blue" not in result


# ── is_profile_setup_done ──


def test_is_profile_setup_done_false_when_empty(prompts_dir):
    assert is_profile_setup_done() is False


def test_is_profile_setup_done_false_when_only_soul(prompts_dir):
    (prompts_dir / "SOUL.md").write_text("# Soul\nI am a helpful assistant with personality.", encoding="utf-8")
    assert is_profile_setup_done() is False


def test_is_profile_setup_done_false_when_only_users(prompts_dir):
    (prompts_dir / "USERS.md").write_text("# Users\nThe user prefers concise answers.", encoding="utf-8")
    assert is_profile_setup_done() is False


def test_is_profile_setup_done_false_when_header_only(prompts_dir):
    """Files with only a markdown header but no real content should not count."""
    (prompts_dir / "SOUL.md").write_text("# Soul\n", encoding="utf-8")
    (prompts_dir / "USERS.md").write_text("# Users\n", encoding="utf-8")
    assert is_profile_setup_done() is False


def test_is_profile_setup_done_true(prompts_dir):
    (prompts_dir / "SOUL.md").write_text(
        "# Soul\nI am a helpful assistant with a warm personality.",
        encoding="utf-8",
    )
    (prompts_dir / "USERS.md").write_text(
        "# Users\nThe user is a software developer who likes Python.",
        encoding="utf-8",
    )
    assert is_profile_setup_done() is True


# ── save_prompt_file ──


def test_save_prompt_file_creates_file(prompts_dir):
    save_prompt_file("TEST.md", "Test content here.")
    assert (prompts_dir / "TEST.md").exists()
    assert (prompts_dir / "TEST.md").read_text(encoding="utf-8") == "Test content here."


def test_save_prompt_file_overwrites(prompts_dir):
    save_prompt_file("OVER.md", "Original")
    save_prompt_file("OVER.md", "Updated")
    assert (prompts_dir / "OVER.md").read_text(encoding="utf-8") == "Updated"


def test_save_prompt_file_creates_dir_if_missing(tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "prompts"
    monkeypatch.setattr("openlama.core.prompt_builder._prompts_dir", lambda: nested)
    save_prompt_file("NEW.md", "Content")
    assert (nested / "NEW.md").exists()
