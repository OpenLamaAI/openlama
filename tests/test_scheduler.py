"""Tests for src/openlama/core/scheduler.py — cron validation and next-run computation."""

import time

from openlama.core.scheduler import compute_next_run, validate_cron_expr


# ── validate_cron_expr ──


def test_validate_cron_expr_valid_every_minute():
    assert validate_cron_expr("* * * * *") is True


def test_validate_cron_expr_valid_daily():
    assert validate_cron_expr("0 10 * * *") is True


def test_validate_cron_expr_valid_weekdays():
    assert validate_cron_expr("0 9 * * 1-5") is True


def test_validate_cron_expr_valid_every_5_min():
    assert validate_cron_expr("*/5 * * * *") is True


def test_validate_cron_expr_valid_monthly():
    assert validate_cron_expr("0 0 1 * *") is True


def test_validate_cron_expr_invalid_garbage():
    assert validate_cron_expr("not a cron") is False


def test_validate_cron_expr_invalid_empty():
    assert validate_cron_expr("") is False


def test_validate_cron_expr_invalid_too_few_fields():
    assert validate_cron_expr("* *") is False


def test_validate_cron_expr_invalid_out_of_range():
    assert validate_cron_expr("99 99 99 99 99") is False


# ── compute_next_run ──


def test_compute_next_run_returns_future_timestamp():
    now = time.time()
    next_run = compute_next_run("* * * * *", base_time=now)
    assert next_run > now


def test_compute_next_run_daily_is_within_24h():
    now = time.time()
    next_run = compute_next_run("0 12 * * *", base_time=now)
    assert next_run > now
    # Should be within 24 hours
    assert next_run - now <= 86400


def test_compute_next_run_uses_current_time_if_zero():
    before = time.time()
    next_run = compute_next_run("* * * * *", base_time=0)
    assert next_run > before


def test_compute_next_run_invalid_returns_zero():
    result = compute_next_run("invalid cron expression")
    assert result == 0


def test_compute_next_run_every_5_minutes():
    base = 1700000000.0  # A fixed timestamp
    next_run = compute_next_run("*/5 * * * *", base_time=base)
    assert next_run > base
    # Next run should be within 5 minutes
    assert next_run - base <= 300
