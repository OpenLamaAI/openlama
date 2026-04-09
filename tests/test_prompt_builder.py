"""Tests for src/openlama/core/prompt_builder.py — system prompt generation and assembly."""

from pathlib import Path

import pytest

from openlama.core.prompt_builder import (
    build_full_system_prompt,
    generate_system_prompt,
    get_prompt_mode,
    is_profile_setup_done,
    save_prompt_file,
    _EXECUTION_BIAS,
)


@pytest.fixture
def prompts_dir(tmp_path, monkeypatch):
    """Set up a temp prompts directory and patch config."""
    d = tmp_path / "prompts"
    d.mkdir()
    monkeypatch.setattr("openlama.core.prompt_builder._prompts_dir", lambda: d)
    return d


# ── get_prompt_mode ──


def test_prompt_mode_full():
    assert get_prompt_mode(32768) == "full"
    assert get_prompt_mode(131072) == "full"
    assert get_prompt_mode(65536) == "full"


def test_prompt_mode_compact():
    assert get_prompt_mode(8192) == "compact"
    assert get_prompt_mode(16384) == "compact"
    assert get_prompt_mode(32767) == "compact"


def test_prompt_mode_minimal():
    assert get_prompt_mode(4096) == "minimal"
    assert get_prompt_mode(2048) == "minimal"
    assert get_prompt_mode(1024) == "minimal"


# ── generate_system_prompt modes ──


def test_generate_full_has_all_sections(prompts_dir):
    result = generate_system_prompt(mode="full")
    assert "# System Prompt" in result
    assert "## CRITICAL RULES" in result
    assert "## Execution Bias" in result
    assert "## Tools" in result
    assert "## Memory" in result
    assert "## Scheduled Tasks" in result
    assert "## Context Management" in result


def test_generate_compact_has_essential_sections(prompts_dir):
    result = generate_system_prompt(mode="compact")
    assert "# System Prompt" in result
    assert "## CRITICAL RULES" in result
    assert "## Execution Bias" in result
    assert "## Memory" in result
    # Should NOT have detailed tool docs or context mgmt
    assert "## Context Management" not in result
    assert "## Tool-Specific Notes" not in result


def test_generate_minimal_is_short(prompts_dir):
    result = generate_system_prompt(mode="minimal")
    assert "## RULES" in result or "## Execution Bias" in result
    assert len(result) < 1500  # Should be well under 1500 chars


def test_generate_default_is_full(prompts_dir):
    result = generate_system_prompt()
    assert "## CRITICAL RULES" in result
    assert "## Tools" in result


# ── Execution Bias presence (CRITICAL for tool usage) ──


def test_execution_bias_in_all_modes(prompts_dir):
    """Execution Bias must be present in ALL prompt modes."""
    for mode in ["full", "compact", "minimal"]:
        result = generate_system_prompt(mode=mode)
        assert "Execution Bias" in result, f"Execution Bias missing in {mode} mode"
        assert "CALL THE TOOL" in result or "Call them directly" in result, \
            f"Tool call instruction missing in {mode} mode"


def test_execution_bias_has_korean_examples(prompts_dir):
    """Execution Bias should include Korean planning examples."""
    result = generate_system_prompt(mode="full")
    assert "검색해드릴게요" in result
    assert "확인해보겠습니다" in result


def test_execution_bias_content():
    """_EXECUTION_BIAS constant should have all required rules."""
    assert "CALL THE TOOL" in _EXECUTION_BIAS
    assert "INCOMPLETE" in _EXECUTION_BIAS
    assert "검색해드릴게요" in _EXECUTION_BIAS


# ── Tool Triggers removed ──


def test_no_tool_triggers_section(prompts_dir):
    """Tool Triggers section should NOT exist (removed for token savings)."""
    for mode in ["full", "compact", "minimal"]:
        result = generate_system_prompt(mode=mode)
        assert "## Tool Triggers" not in result, f"Tool Triggers still in {mode} mode"


# ── Compact mode is smaller than full ──


def test_compact_smaller_than_full(prompts_dir):
    full = generate_system_prompt(mode="full")
    compact = generate_system_prompt(mode="compact")
    # Compact should be significantly smaller
    assert len(compact) < len(full) * 0.7, \
        f"Compact ({len(compact)}) not significantly smaller than full ({len(full)})"


def test_minimal_smaller_than_compact(prompts_dir):
    compact = generate_system_prompt(mode="compact")
    minimal = generate_system_prompt(mode="minimal")
    assert len(minimal) < len(compact) * 0.8, \
        f"Minimal ({len(minimal)}) not significantly smaller than compact ({len(compact)})"


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


def test_build_full_system_prompt_includes_datetime(prompts_dir):
    """System prompt should include current date/time."""
    result = build_full_system_prompt()
    assert "Current date/time:" in result


def test_build_full_system_prompt_no_double_datetime(prompts_dir):
    """Date/time should appear exactly once."""
    result = build_full_system_prompt()
    count = result.count("Current date/time:")
    assert count == 1, f"Date/time appears {count} times, expected 1"


def test_build_full_system_prompt_uses_num_ctx(prompts_dir):
    """Different num_ctx values should produce different prompt sizes."""
    full = build_full_system_prompt(num_ctx=32768)
    compact = build_full_system_prompt(num_ctx=8192)
    minimal = build_full_system_prompt(num_ctx=4096)
    assert len(full) > len(compact) > len(minimal)


def test_build_full_system_prompt_minimal_truncates_soul(prompts_dir):
    """Minimal mode should truncate SOUL.md to 200 chars."""
    long_soul = "# Soul\n" + "x" * 500
    (prompts_dir / "SOUL.md").write_text(long_soul, encoding="utf-8")
    result = build_full_system_prompt(num_ctx=4096)  # minimal mode
    # Soul content should be truncated — at most 200 chars from the raw text
    assert "x" * 300 not in result
    # But some x's should remain (truncated version)
    assert "x" * 100 in result


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


# ── Lazy skill loading ──


def test_full_mode_has_skills_with_file_paths(prompts_dir, tmp_path, monkeypatch):
    """Full mode should list skills with file paths for lazy loading."""
    from openlama.core.skills import save_skill, _invalidate_cache
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr("openlama.core.skills._skills_dir", lambda: skills_dir)
    _invalidate_cache()
    save_skill("test_skill", "A test skill", "test", "Instructions")
    result = generate_system_prompt(mode="full")
    assert "Available Skills" in result
    assert "file_read" in result or "SKILL.md" in result
    _invalidate_cache()
