"""Tests for formatting module – markdown conversion, message splitting."""

from utils.formatting import convert_markdown, split_message, format_think_response, chunks


def test_convert_markdown_empty():
    text, entities = convert_markdown("")
    assert text == ""
    assert entities == []


def test_convert_markdown_plain():
    text, entities = convert_markdown("Hello world")
    assert "Hello world" in text


def test_convert_markdown_bold():
    text, entities = convert_markdown("**bold text**")
    assert "bold text" in text
    assert len(entities) > 0


def test_convert_markdown_code():
    text, entities = convert_markdown("`inline code`")
    assert "inline code" in text


def test_convert_markdown_code_block():
    text, entities = convert_markdown("```python\nprint('hello')\n```")
    assert "print" in text


def test_convert_markdown_link():
    text, entities = convert_markdown("[Google](https://google.com)")
    assert "Google" in text


def test_convert_markdown_heading():
    text, entities = convert_markdown("# Title")
    assert "Title" in text


def test_convert_markdown_list():
    text, entities = convert_markdown("- item1\n- item2\n- item3")
    assert "item1" in text
    assert "item2" in text


# ── split_message ──

def test_split_message_short():
    text = "Short message"
    text_conv, ents = convert_markdown(text)
    parts = split_message(text_conv, ents)
    assert len(parts) == 1


def test_split_message_long():
    text = "A" * 5000  # Exceeds TELEGRAM_MAX_MSG
    text_conv, ents = convert_markdown(text)
    parts = split_message(text_conv, ents)
    assert len(parts) >= 2


# ── format_think_response ──

def test_format_think_response():
    text, entities = format_think_response("thinking process", "final answer")
    assert "thinking process" in text
    assert "final answer" in text
    assert len(entities) > 0  # Should have blockquote entity


def test_format_think_response_empty_thinking():
    text, entities = format_think_response("", "just answer")
    assert "just answer" in text


# ── chunks (legacy) ──

def test_chunks_short():
    result = chunks("short text")
    assert result == ["short text"]


def test_chunks_long():
    long_text = "A" * 10000
    result = chunks(long_text, size=4096)
    assert len(result) >= 3
    joined = "".join(result)
    assert len(joined) == 10000
