"""Tests for database module – schema, CRUD, context management."""

import json

from database import (
    ModelSettings,
    UserState,
    clear_context,
    get_model_settings,
    get_setting,
    get_user,
    init_db,
    is_authed,
    is_login_locked,
    load_context,
    log_tool_call,
    now_ts,
    reset_model_settings,
    save_context,
    set_model_setting,
    set_setting,
    update_user,
)


def test_init_db_idempotent():
    """init_db can be called multiple times safely."""
    init_db()
    init_db()


def test_get_user_creates_new():
    user = get_user(999999)
    assert isinstance(user, UserState)
    assert user.telegram_id == 999999
    assert user.auth_until == 0
    assert user.state == ""


def test_update_user():
    uid = 100001
    get_user(uid)
    update_user(uid, state="await_password", login_fail_count=3)
    user = get_user(uid)
    assert user.state == "await_password"
    assert user.login_fail_count == 3


def test_is_authed():
    uid = 100002
    get_user(uid)
    update_user(uid, auth_until=now_ts() + 3600)
    user = get_user(uid)
    assert is_authed(user) is True

    update_user(uid, auth_until=0)
    user = get_user(uid)
    assert is_authed(user) is False


def test_is_login_locked():
    uid = 100003
    get_user(uid)
    update_user(uid, login_lock_until=now_ts() + 600)
    user = get_user(uid)
    assert is_login_locked(user) is True

    update_user(uid, login_lock_until=0)
    user = get_user(uid)
    assert is_login_locked(user) is False


def test_system_prompt():
    uid = 100004
    get_user(uid)
    update_user(uid, system_prompt="You are a helpful bot.")
    user = get_user(uid)
    assert user.system_prompt == "You are a helpful bot."


def test_think_mode():
    uid = 100005
    get_user(uid)
    update_user(uid, think_mode=1)
    user = get_user(uid)
    assert user.think_mode == 1


def test_context_turns_and_ttl():
    uid = 100006
    get_user(uid)
    update_user(uid, context_turns=20, context_ttl_sec=3600)
    user = get_user(uid)
    assert user.context_turns == 20
    assert user.context_ttl_sec == 3600


# ── Context CRUD ──

def test_save_and_load_context():
    uid = 200001
    items = [{"u": "hello", "a": "hi"}, {"u": "how are you", "a": "fine"}]
    save_context(uid, items, max_turns=10)
    loaded = load_context(uid, max_turns=10, ttl=9999)
    assert len(loaded) == 2
    assert loaded[0]["u"] == "hello"


def test_context_max_turns_trim():
    uid = 200002
    items = [{"u": f"q{i}", "a": f"a{i}"} for i in range(20)]
    save_context(uid, items, max_turns=5)
    loaded = load_context(uid, max_turns=5, ttl=9999)
    assert len(loaded) == 5
    assert loaded[0]["u"] == "q15"


def test_clear_context():
    uid = 200003
    save_context(uid, [{"u": "test", "a": "test"}], max_turns=10)
    clear_context(uid)
    loaded = load_context(uid, max_turns=10, ttl=9999)
    assert loaded == []


def test_context_ttl_expiry():
    uid = 200004
    save_context(uid, [{"u": "old", "a": "data"}], max_turns=10)
    # TTL=0 means already expired, but since save just happened,
    # updated_at == now, so (now - updated_at) == 0 which is NOT > 0.
    # Use ttl=-1 to force expiry
    loaded = load_context(uid, max_turns=10, ttl=-1)
    assert loaded == []


# ── Settings (global key-value) ──

def test_settings_crud():
    set_setting("test_key", "test_value")
    assert get_setting("test_key") == "test_value"

    set_setting("test_key", "updated")
    assert get_setting("test_key") == "updated"


def test_get_nonexistent_setting():
    assert get_setting("nonexistent_key_xyz") is None


# ── Model Settings ──

def test_model_settings_defaults():
    ms = get_model_settings(300001)
    assert isinstance(ms, ModelSettings)
    assert ms.temperature == 0.7
    assert ms.num_ctx == 8192


def test_set_model_setting():
    uid = 300002
    set_model_setting(uid, "test-model", "temperature", 0.5)
    ms = get_model_settings(uid, "test-model")
    assert ms.temperature == 0.5


def test_reset_model_settings():
    uid = 300003
    set_model_setting(uid, "test-model", "temperature", 0.1)
    reset_model_settings(uid, "test-model")
    ms = get_model_settings(uid, "test-model")
    assert ms.temperature == 0.7  # Back to default


# ── Tool call logging ──

def test_log_tool_call():
    """Tool call logging should not raise."""
    log_tool_call(400001, "web_search", {"query": "test"}, "result", success=True)
    log_tool_call(400001, "calculator", {"expression": "1+1"}, "2", success=True)
    log_tool_call(400001, "broken_tool", {}, "error", success=False)
