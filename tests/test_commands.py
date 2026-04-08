"""Tests for src/openlama/core/commands.py — command registry, lookup, and help formatting."""

from openlama.core.commands import (
    COMMANDS,
    find_command,
    format_help_text,
    get_all_command_names,
    get_commands_by_category,
)


# ── get_commands_by_category ──


def test_get_commands_by_category_returns_all_categories():
    groups = get_commands_by_category()
    expected = {"chat", "model", "settings", "system", "admin"}
    assert set(groups.keys()) == expected


def test_get_commands_by_category_lists_not_empty():
    groups = get_commands_by_category()
    for cat, cmds in groups.items():
        assert len(cmds) > 0, f"Category '{cat}' should have at least one command"


def test_get_commands_by_category_total_matches():
    groups = get_commands_by_category()
    total = sum(len(cmds) for cmds in groups.values())
    assert total == len(COMMANDS)


# ── find_command ──


def test_find_command_existing():
    cmd = find_command("help")
    assert cmd is not None
    assert cmd["name"] == "help"
    assert cmd["category"] == "chat"


def test_find_command_model():
    cmd = find_command("model")
    assert cmd is not None
    assert cmd["category"] == "model"


def test_find_command_nonexistent():
    assert find_command("nonexistent_command_xyz") is None


def test_find_command_admin():
    cmd = find_command("login")
    assert cmd is not None
    assert cmd["category"] == "admin"


# ── get_all_command_names ──


def test_get_all_command_names_returns_all():
    names = get_all_command_names()
    assert isinstance(names, list)
    assert len(names) == len(COMMANDS)
    assert "help" in names
    assert "model" in names
    assert "login" in names
    assert "cron" in names


def test_get_all_command_names_are_strings():
    names = get_all_command_names()
    for n in names:
        assert isinstance(n, str)


# ── format_help_text ──


def test_format_help_text_contains_all_categories():
    text = format_help_text()
    assert "Chat:" in text
    assert "Model:" in text
    assert "Settings:" in text
    assert "System:" in text
    assert "Account:" in text


def test_format_help_text_contains_commands():
    text = format_help_text()
    assert "/help" in text
    assert "/model" in text
    assert "/login" in text


def test_format_help_text_with_exclusions():
    text = format_help_text(exclude=["quit", "login", "logout", "setpassword"])
    assert "/quit" not in text
    assert "/login" not in text
    assert "/help" in text  # Not excluded


def test_format_help_text_exclude_all_in_category():
    """Excluding all commands in a category should omit that category header."""
    admin_cmds = [c["name"] for c in COMMANDS if c["category"] == "admin"]
    text = format_help_text(exclude=admin_cmds)
    assert "Account:" not in text
    # Other categories should still be present
    assert "Chat:" in text


def test_format_help_text_exclude_empty_list():
    text_no_exclude = format_help_text()
    text_empty = format_help_text(exclude=[])
    assert text_no_exclude == text_empty
