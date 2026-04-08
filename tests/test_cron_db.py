"""Tests for cron job CRUD in src/openlama/database.py."""

import time

from openlama.database import (
    create_cron_job,
    delete_cron_job,
    get_cron_job,
    get_due_cron_jobs,
    init_db,
    list_cron_jobs,
    update_cron_job,
)


# The conftest _temp_db fixture auto-inits the legacy DB.
# We also need to init the openlama DB for these tests.

import pytest

@pytest.fixture(autouse=True)
def _init_openlama_db(tmp_path, monkeypatch):
    """Point openlama.database.DB_PATH to a temp file and init."""
    import openlama.database as oldb
    db_path = tmp_path / "openlama_test.db"
    monkeypatch.setattr(oldb, "DB_PATH", db_path)
    init_db()


# ── create_cron_job ──


def test_create_cron_job_returns_id():
    job_id = create_cron_job("*/5 * * * *", "check server", chat_id=123, created_by=1)
    assert isinstance(job_id, int)
    assert job_id > 0


def test_create_multiple_cron_jobs():
    id1 = create_cron_job("0 * * * *", "task1")
    id2 = create_cron_job("0 0 * * *", "task2")
    assert id2 > id1


# ── list_cron_jobs ──


def test_list_cron_jobs_empty():
    jobs = list_cron_jobs()
    assert jobs == []


def test_list_cron_jobs_returns_all():
    create_cron_job("* * * * *", "job1")
    create_cron_job("0 * * * *", "job2")
    jobs = list_cron_jobs()
    assert len(jobs) == 2


def test_list_cron_jobs_enabled_only():
    id1 = create_cron_job("* * * * *", "enabled_job")
    id2 = create_cron_job("0 * * * *", "disabled_job")
    update_cron_job(id2, enabled=0)

    all_jobs = list_cron_jobs(enabled_only=False)
    enabled_jobs = list_cron_jobs(enabled_only=True)
    assert len(all_jobs) == 2
    assert len(enabled_jobs) == 1
    assert enabled_jobs[0]["task"] == "enabled_job"


# ── get_cron_job ──


def test_get_cron_job_by_id():
    job_id = create_cron_job("30 8 * * 1", "Monday report", channel="telegram", chat_id=456)
    job = get_cron_job(job_id)
    assert job is not None
    assert job["cron_expr"] == "30 8 * * 1"
    assert job["task"] == "Monday report"
    assert job["chat_id"] == 456


def test_get_cron_job_nonexistent():
    assert get_cron_job(99999) is None


# ── delete_cron_job ──


def test_delete_cron_job_removes_it():
    job_id = create_cron_job("* * * * *", "to_delete")
    assert delete_cron_job(job_id) is True
    assert get_cron_job(job_id) is None


def test_delete_cron_job_nonexistent():
    assert delete_cron_job(99999) is False


# ── update_cron_job ──


def test_update_cron_job_modifies_fields():
    job_id = create_cron_job("* * * * *", "original task")
    now = int(time.time())
    update_cron_job(job_id, task="updated task", last_run=now, next_run=now + 60)

    job = get_cron_job(job_id)
    assert job["task"] == "updated task"
    assert job["last_run"] == now
    assert job["next_run"] == now + 60


def test_update_cron_job_enable_disable():
    job_id = create_cron_job("* * * * *", "toggle job")
    update_cron_job(job_id, enabled=0)
    job = get_cron_job(job_id)
    assert job["enabled"] == 0

    update_cron_job(job_id, enabled=1)
    job = get_cron_job(job_id)
    assert job["enabled"] == 1


def test_update_cron_job_no_kwargs():
    """update_cron_job with no kwargs should not raise."""
    job_id = create_cron_job("* * * * *", "no-op")
    update_cron_job(job_id)  # Should be a no-op
    job = get_cron_job(job_id)
    assert job["task"] == "no-op"


# ── get_due_cron_jobs ──


def test_get_due_cron_jobs_returns_due():
    now = int(time.time())
    # Due job: next_run in the past
    id1 = create_cron_job("* * * * *", "due job", next_run=now - 60)
    # Not yet due: next_run in the future
    id2 = create_cron_job("* * * * *", "future job", next_run=now + 3600)
    # Disabled job: should not appear even if due
    id3 = create_cron_job("* * * * *", "disabled due", next_run=now - 60)
    update_cron_job(id3, enabled=0)

    due = get_due_cron_jobs(now)
    assert len(due) == 1
    assert due[0]["task"] == "due job"


def test_get_due_cron_jobs_excludes_zero_next_run():
    """Jobs with next_run=0 should not be considered due."""
    now = int(time.time())
    create_cron_job("* * * * *", "zero next_run", next_run=0)
    due = get_due_cron_jobs(now)
    assert len(due) == 0


def test_get_due_cron_jobs_empty():
    now = int(time.time())
    due = get_due_cron_jobs(now)
    assert due == []
