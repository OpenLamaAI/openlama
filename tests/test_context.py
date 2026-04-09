"""Tests for context management — language-aware token estimation, auto-compaction."""

import pytest

from openlama.core.context import _estimate_tokens, _estimate_messages_tokens, build_context_bar


# ── Language-aware token estimation ──


def test_estimate_tokens_empty():
    assert _estimate_tokens("") == 1  # min 1


def test_estimate_tokens_int_legacy():
    """Legacy int path: callers passing character count."""
    assert _estimate_tokens(0) == 1  # min 1
    assert _estimate_tokens(30) == 10  # 30 // 3
    assert _estimate_tokens(300) == 100  # 300 // 3


def test_estimate_tokens_english():
    # Pure English: ~4 chars per token
    text = "Hello world this is a test"  # 26 chars → ~6-7 tokens
    est = _estimate_tokens(text)
    assert 5 <= est <= 10, f"English estimate {est} out of expected range"


def test_estimate_tokens_korean():
    # Pure Korean: ~1.5 chars per token
    text = "안녕하세요 반갑습니다 테스트입니다"  # 17 chars → ~11 tokens
    est = _estimate_tokens(text)
    assert 8 <= est <= 15, f"Korean estimate {est} out of expected range"


def test_estimate_tokens_mixed():
    # Mixed: should handle both
    text = "Hello 안녕하세요 world 테스트"  # Mix of English and Korean
    est = _estimate_tokens(text)
    assert est > 0


def test_estimate_tokens_korean_more_than_english_per_char():
    """Korean text should estimate MORE tokens per character than English."""
    # Same number of characters but different languages
    korean = "가나다라마바사아자차"  # 10 CJK chars
    english = "abcdefghij"  # 10 ASCII chars

    korean_est = _estimate_tokens(korean)
    english_est = _estimate_tokens(english)

    # Korean should produce more tokens per char
    assert korean_est > english_est, \
        f"Korean ({korean_est}) should estimate more tokens than English ({english_est})"


def test_estimate_tokens_cjk_formula():
    """Verify CJK uses ~1.5 chars/token and Latin uses ~4 chars/token."""
    # Pure CJK: 150 chars → ~100 tokens (150/1.5)
    cjk_text = "가" * 150
    est = _estimate_tokens(cjk_text)
    assert 90 <= est <= 110, f"CJK estimate {est}, expected ~100"

    # Pure Latin: 400 chars → ~100 tokens (400/4)
    latin_text = "a" * 400
    est = _estimate_tokens(latin_text)
    assert 90 <= est <= 110, f"Latin estimate {est}, expected ~100"


# ── _estimate_messages_tokens ──


def test_estimate_messages_tokens_empty():
    est = _estimate_messages_tokens("", [], "")
    assert est >= 1  # min 1


def test_estimate_messages_tokens_basic():
    est = _estimate_messages_tokens(
        "system prompt text",
        [{"u": "hello", "a": "world"}],
        "user text",
    )
    assert est > 0


def test_estimate_messages_tokens_scales_with_content():
    small = _estimate_messages_tokens("sys", [{"u": "q", "a": "a"}], "q")
    large = _estimate_messages_tokens(
        "system prompt " * 100,
        [{"u": "question " * 50, "a": "answer " * 50} for _ in range(5)],
        "new question " * 10,
    )
    assert large > small * 5


# ── build_context_bar ──


def test_context_bar_format():
    bar = build_context_bar(4096, 8192, 5)
    assert "%" in bar
    assert "tokens" in bar
    assert "turns: 5" in bar


def test_context_bar_empty():
    bar = build_context_bar(0, 8192, 0)
    assert "0.0%" in bar


def test_context_bar_full():
    bar = build_context_bar(8192, 8192, 10)
    assert "100.0%" in bar


# ── Compaction threshold ──


def test_compaction_threshold_small_ctx():
    """Small context should NOT trigger compaction."""
    ctx = [{"u": "hi", "a": "hello"}]
    est = _estimate_messages_tokens("system prompt", ctx, "question")
    threshold = int(8192 * 0.7)
    assert est < threshold


def test_compaction_threshold_large_ctx():
    """Large context SHOULD trigger compaction with small num_ctx."""
    ctx = [{"u": "question " * 200, "a": "answer " * 200} for _ in range(10)]
    est = _estimate_messages_tokens("system prompt", ctx, "new question")
    threshold_8k = int(8192 * 0.7)
    assert est > threshold_8k, f"Expected {est} > {threshold_8k}"


def test_compaction_threshold_scales_with_num_ctx():
    """Same context may NOT trigger compaction with larger num_ctx."""
    ctx = [{"u": "question " * 200, "a": "answer " * 200} for _ in range(10)]
    est = _estimate_messages_tokens("sys", ctx, "q")
    threshold_128k = int(131072 * 0.7)
    assert est < threshold_128k
