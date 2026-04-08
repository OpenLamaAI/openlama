"""Tests for src/openlama/doctor.py — health check utilities."""

import os
from pathlib import Path

import pytest

from openlama.doctor import (
    CheckResult,
    DoctorReport,
    check_data_dir,
    check_database,
    check_disk_space,
    check_python_deps,
)


# ── DoctorReport properties ──


def test_doctor_report_empty():
    report = DoctorReport()
    assert report.ok_count == 0
    assert report.warn_count == 0
    assert report.fail_count == 0
    assert report.fixable_count == 0


def test_doctor_report_ok_count():
    report = DoctorReport(results=[
        CheckResult("a", "ok", "fine"),
        CheckResult("b", "ok", "good"),
        CheckResult("c", "fail", "bad"),
    ])
    assert report.ok_count == 2


def test_doctor_report_warn_count():
    report = DoctorReport(results=[
        CheckResult("a", "warn", "hmm"),
        CheckResult("b", "ok", "good"),
        CheckResult("c", "warn", "hmm2"),
    ])
    assert report.warn_count == 2


def test_doctor_report_fail_count():
    report = DoctorReport(results=[
        CheckResult("a", "fail", "bad"),
        CheckResult("b", "fail", "worse"),
        CheckResult("c", "ok", "fine"),
    ])
    assert report.fail_count == 2


def test_doctor_report_fixable_count():
    report = DoctorReport(results=[
        CheckResult("a", "fail", "bad", fixable=True),
        CheckResult("b", "warn", "hmm", fixable=True),
        CheckResult("c", "ok", "fine", fixable=True),  # ok + fixable doesn't count
        CheckResult("d", "fail", "bad", fixable=False),
    ])
    assert report.fixable_count == 2


def test_doctor_report_mixed():
    report = DoctorReport(results=[
        CheckResult("a", "ok", "fine"),
        CheckResult("b", "warn", "hmm", fixable=True),
        CheckResult("c", "fail", "bad", fixable=True),
        CheckResult("d", "fail", "bad2", fixable=False),
    ])
    assert report.ok_count == 1
    assert report.warn_count == 1
    assert report.fail_count == 2
    assert report.fixable_count == 2


# ── check_data_dir ──


def test_check_data_dir_ok(tmp_path, monkeypatch):
    monkeypatch.setattr("openlama.doctor.DATA_DIR", tmp_path)
    result = check_data_dir()
    assert result.status == "ok"
    assert result.name == "Data directory"


def test_check_data_dir_missing(tmp_path, monkeypatch):
    missing = tmp_path / "nonexistent"
    monkeypatch.setattr("openlama.doctor.DATA_DIR", missing)
    result = check_data_dir()
    assert result.status == "fail"
    assert result.fixable is True


def test_check_data_dir_not_writable(tmp_path, monkeypatch):
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o444)
    monkeypatch.setattr("openlama.doctor.DATA_DIR", readonly)
    result = check_data_dir()
    assert result.status == "fail"
    assert result.fixable is False
    # Restore permissions for cleanup
    readonly.chmod(0o755)


# ── check_database ──


def test_check_database_ok(tmp_path, monkeypatch):
    """A properly initialized DB should return ok."""
    monkeypatch.setattr("openlama.doctor.DATA_DIR", tmp_path)
    import openlama.database as oldb
    monkeypatch.setattr(oldb, "DB_PATH", tmp_path / "openlama.db")
    from openlama.database import init_db
    init_db()
    result = check_database()
    assert result.status == "ok"


def test_check_database_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("openlama.doctor.DATA_DIR", tmp_path)
    # No DB file exists
    result = check_database()
    assert result.status == "fail"
    assert result.fixable is True


def test_check_database_missing_tables(tmp_path, monkeypatch):
    """DB exists but missing required tables."""
    import sqlite3
    monkeypatch.setattr("openlama.doctor.DATA_DIR", tmp_path)
    db_path = tmp_path / "openlama.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE dummy (id INTEGER)")
    conn.close()
    result = check_database()
    assert result.status == "warn"
    assert result.fixable is True


# ── check_python_deps ──


def test_check_python_deps_ok():
    """In our test environment, all critical deps should be installed."""
    result = check_python_deps()
    # At minimum telegram, httpx, click, rich should be available
    assert result.status in ("ok", "fail")
    assert result.name == "Python dependencies"


# ── check_disk_space ──


def test_check_disk_space_ok(tmp_path, monkeypatch):
    monkeypatch.setattr("openlama.doctor.DATA_DIR", tmp_path)
    result = check_disk_space()
    assert result.status in ("ok", "warn")
    assert result.name == "Disk space"
    assert "GB" in result.message or "skipped" in result.message.lower()


# ── CheckResult dataclass ──


def test_check_result_defaults():
    r = CheckResult("test", "ok", "all good")
    assert r.fixable is False
    assert r.fix_action == ""


def test_check_result_with_fix():
    r = CheckResult("test", "fail", "broken", fixable=True, fix_action="Fix it")
    assert r.fixable is True
    assert r.fix_action == "Fix it"
