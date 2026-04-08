"""Tests for SlashCompleter — dynamic slash command autocomplete."""

from prompt_toolkit.document import Document

from openlama.channels.cli.chat import SlashCompleter


def _fmt_to_str(fmt) -> str:
    """Convert FormattedText or str to plain string."""
    if isinstance(fmt, str):
        return fmt
    # FormattedText is a list of (style, text) tuples
    try:
        return "".join(t for _, t in fmt)
    except (TypeError, ValueError):
        return str(fmt)


def _get_completions(text: str) -> list[dict]:
    """Helper: get completions for a given input text."""
    completer = SlashCompleter()
    doc = Document(text, len(text))
    return [
        {"text": c.text, "display": _fmt_to_str(c.display), "meta": _fmt_to_str(c.display_meta)}
        for c in completer.get_completions(doc, None)
    ]


# ── Activation ──


def test_no_completions_for_plain_text():
    """Plain text should not trigger completions."""
    assert _get_completions("hello") == []
    assert _get_completions("how are you") == []


def test_no_completions_for_empty():
    assert _get_completions("") == []


def test_slash_shows_all_commands():
    """Just '/' should show all non-excluded commands."""
    results = _get_completions("/")
    names = [r["text"] for r in results]
    assert "help" in names
    assert "status" in names
    assert "model" in names
    assert "quit" in names
    # Admin commands should be excluded
    assert "login" not in names
    assert "logout" not in names
    assert "setpassword" not in names


# ── Filtering ──


def test_prefix_filter_s():
    """'/s' should match status, settings, skills, systemprompt."""
    results = _get_completions("/s")
    names = [r["text"] for r in results]
    assert "status" in names
    assert "settings" in names
    assert "skills" in names
    assert "systemprompt" in names
    # Non-matching
    assert "help" not in names
    assert "model" not in names


def test_prefix_filter_sk():
    """'/sk' should match only skills."""
    results = _get_completions("/sk")
    names = [r["text"] for r in results]
    assert names == ["skills"]


def test_prefix_filter_mo():
    """'/mo' should match model and models."""
    results = _get_completions("/mo")
    names = [r["text"] for r in results]
    assert "model" in names
    assert "models" in names
    assert len(names) == 2


def test_prefix_filter_no_match():
    """'/xyz' should return no completions."""
    assert _get_completions("/xyz") == []


def test_exact_command_still_completes():
    """'/help' should still show 'help' as completion."""
    results = _get_completions("/help")
    names = [r["text"] for r in results]
    assert "help" in names


# ── Display ──


def test_display_includes_slash():
    """Display should show '/command' format."""
    results = _get_completions("/h")
    help_result = [r for r in results if r["text"] == "help"][0]
    assert help_result["display"] == "/help"


def test_meta_has_description():
    """Meta should contain the command description."""
    results = _get_completions("/h")
    help_result = [r for r in results if r["text"] == "help"][0]
    assert help_result["meta"]  # Should have some description
    assert isinstance(help_result["meta"], str)


# ── Edge cases ──


def test_case_insensitive_prefix():
    """Prefix matching should be case-insensitive."""
    results_lower = _get_completions("/s")
    results_upper = _get_completions("/S")
    # Both should return same commands
    names_lower = sorted([r["text"] for r in results_lower])
    names_upper = sorted([r["text"] for r in results_upper])
    assert names_lower == names_upper


def test_single_char_filter():
    """'/c' should match clear, cron."""
    results = _get_completions("/c")
    names = [r["text"] for r in results]
    assert "clear" in names
    assert "cron" in names
