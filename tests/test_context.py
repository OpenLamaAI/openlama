"""Tests for context management – token estimation, auto-compaction."""

import pytest

from handlers.chat import _estimate_tokens, _estimate_messages_tokens


def test_estimate_tokens_basic():
    assert _estimate_tokens(0) == 1  # min 1
    assert _estimate_tokens(30) == 10
    assert _estimate_tokens(300) == 100


def test_estimate_tokens_korean():
    # Korean text: ~3 chars/token is a reasonable estimate
    korean = "안녕하세요 반갑습니다 테스트입니다"  # 17 chars
    est = _estimate_tokens(len(korean))
    assert est >= 1
    assert est <= 17


def test_estimate_messages_tokens_empty():
    est = _estimate_messages_tokens("", [], "")
    assert est == 1  # min 1


def test_estimate_messages_tokens_basic():
    est = _estimate_messages_tokens(
        "system prompt",
        [{"u": "hello", "a": "world"}],
        "user text",
    )
    assert est > 0
    total_chars = len("system prompt") + len("hello") + len("world") + len("user text")
    assert est == max(1, total_chars // 3)


def test_estimate_messages_tokens_with_summary():
    est_no_summary = _estimate_messages_tokens("sys", [], "user")
    est_with_summary = _estimate_messages_tokens("sys", [], "user", summary="This is a summary of previous conversation")
    assert est_with_summary > est_no_summary


def test_estimate_messages_tokens_many_turns():
    ctx = [{"u": "question " * 100, "a": "answer " * 100} for _ in range(10)]
    est = _estimate_messages_tokens("system", ctx, "new question")
    assert est > 1000  # Should be substantial


# ── Auto-compaction threshold logic ──

def test_compaction_threshold_small_ctx():
    """Small context should NOT trigger compaction."""
    from handlers.chat import _estimate_messages_tokens
    ctx = [{"u": "hi", "a": "hello"}]
    est = _estimate_messages_tokens("sys", ctx, "q")
    threshold = int(8192 * 0.6)
    assert est < threshold


def test_compaction_threshold_large_ctx():
    """Large context SHOULD trigger compaction with small num_ctx."""
    ctx = [{"u": "question " * 200, "a": "answer " * 200} for _ in range(10)]
    est = _estimate_messages_tokens("system prompt", ctx, "new question")
    threshold_8k = int(8192 * 0.6)  # ~4915
    assert est > threshold_8k, f"Expected {est} > {threshold_8k}"


def test_compaction_threshold_scales_with_num_ctx():
    """Same context may NOT trigger compaction with larger num_ctx."""
    ctx = [{"u": "question " * 200, "a": "answer " * 200} for _ in range(10)]
    est = _estimate_messages_tokens("sys", ctx, "q")
    threshold_128k = int(131072 * 0.6)
    # With 128K context, this moderate amount should NOT trigger
    assert est < threshold_128k
