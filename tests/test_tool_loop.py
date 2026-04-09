"""Tests for tool loop detection — prevents runaway identical tool calling."""

import pytest

from openlama.core.tool_loop import (
    LoopDetector,
    _hash,
    _count_ping_pong,
    ToolCallRecord,
    WARNING_THRESHOLD,
    CRITICAL_THRESHOLD,
)


# ── Basic hashing ──


def test_hash_deterministic():
    assert _hash({"a": 1}) == _hash({"a": 1})


def test_hash_different_for_different_input():
    assert _hash({"a": 1}) != _hash({"a": 2})


def test_hash_dict_order_independent():
    assert _hash({"a": 1, "b": 2}) == _hash({"b": 2, "a": 1})


def test_hash_string():
    assert _hash("hello") == _hash("hello")
    assert _hash("hello") != _hash("world")


# ── LoopDetector — no warnings for normal usage ──


def test_no_warning_for_different_calls():
    d = LoopDetector()
    for i in range(20):
        w = d.record(f"tool_{i}", {"arg": i}, f"result_{i}")
        assert w is None


def test_no_warning_for_few_repeats():
    d = LoopDetector()
    for i in range(WARNING_THRESHOLD - 1):
        w = d.record("web_search", {"query": "python"}, f"result_{i}")
        assert w is None


# ── LoopDetector — generic repeat detection ──


def test_warning_on_repeated_calls_with_no_progress():
    """Same tool + same args + same result should trigger WARNING."""
    d = LoopDetector()
    for i in range(WARNING_THRESHOLD):
        w = d.record("web_search", {"query": "python"}, "same result")
    assert w is not None
    assert "WARNING" in w
    assert "web_search" in w


def test_critical_on_many_repeated_calls():
    """Same tool + same args repeated CRITICAL_THRESHOLD times → CRITICAL."""
    d = LoopDetector()
    w = None
    for i in range(CRITICAL_THRESHOLD):
        w = d.record("file_read", {"path": "/tmp/test"}, "content")
    assert w is not None
    assert "CRITICAL" in w
    assert "file_read" in w


def test_no_warning_when_results_differ():
    """Same tool + same args but different results = progress, no warning."""
    d = LoopDetector()
    for i in range(WARNING_THRESHOLD + 2):
        w = d.record("web_search", {"query": "python"}, f"result_{i}")
    # The generic_repeat CRITICAL threshold may fire at 10,
    # but the no_progress WARNING should not fire if results differ
    # Actually at CRITICAL_THRESHOLD the generic repeat fires regardless
    # So let's test below CRITICAL but above WARNING
    d2 = LoopDetector()
    for i in range(WARNING_THRESHOLD + 1):
        w = d2.record("web_search", {"query": "python"}, f"different_result_{i}")
    # WARNING requires same results too, so this should be None
    # (unless it hit CRITICAL which requires same_call_count >= CRITICAL_THRESHOLD)
    if WARNING_THRESHOLD + 1 < CRITICAL_THRESHOLD:
        assert w is None


# ── LoopDetector — ping-pong detection ──


def test_ping_pong_detection():
    """Alternating A-B-A-B pattern should trigger warning."""
    d = LoopDetector()
    w = None
    for i in range(WARNING_THRESHOLD * 2):
        if i % 2 == 0:
            w = d.record("tool_a", {"x": 1}, "result_a")
        else:
            w = d.record("tool_b", {"y": 2}, "result_b")
    assert w is not None
    assert "alternating" in w.lower() or "WARNING" in w


def test_no_ping_pong_with_three_tools():
    """A-B-C-A-B-C is not ping-pong. Use different args to avoid generic_repeat."""
    d = LoopDetector()
    w = None
    for i in range(12):
        tool = ["a", "b", "c"][i % 3]
        w = d.record(f"tool_{tool}", {"x": i}, f"result_{tool}_{i}")
    # No pattern should be detected since each call is unique
    assert w is None


# ── LoopDetector — reset ──


def test_reset_clears_history():
    d = LoopDetector()
    for i in range(WARNING_THRESHOLD - 1):
        d.record("tool", {"a": 1}, "result")
    d.reset()
    # After reset, counter starts from scratch
    w = d.record("tool", {"a": 1}, "result")
    assert w is None


# ── _count_ping_pong helper ──


def test_count_ping_pong_simple():
    records = [
        ToolCallRecord("a", "a:h1", "r1"),
        ToolCallRecord("b", "b:h2", "r2"),
        ToolCallRecord("a", "a:h1", "r1"),
        ToolCallRecord("b", "b:h2", "r2"),
    ]
    assert _count_ping_pong(records) == 2


def test_count_ping_pong_none():
    """A-B-C-D should not be detected as ping-pong."""
    records = [
        ToolCallRecord("a", "a:h1", "r1"),
        ToolCallRecord("b", "b:h2", "r2"),
        ToolCallRecord("c", "c:h3", "r3"),
        ToolCallRecord("d", "d:h4", "r4"),
    ]
    # The last pair is c:h3, d:h4 — and looking backward, index 1 has b:h2 != d:h4
    # So this should NOT match ping-pong (only 1 pair at most)
    pp = _count_ping_pong(records)
    assert pp <= 1, f"Expected 0 or 1 for A-B-C-D, got {pp}"


def test_count_ping_pong_short():
    records = [ToolCallRecord("a", "a:h1", "r1")]
    assert _count_ping_pong(records) == 0
