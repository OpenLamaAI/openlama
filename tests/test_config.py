"""Tests for config module – verify all config values load correctly."""

from pathlib import Path


def test_telegram_config():
    from config import BOT_TOKEN, ADMIN_PASSWORD, TELEGRAM_MAX_MSG
    assert isinstance(BOT_TOKEN, str)
    assert isinstance(ADMIN_PASSWORD, str)
    assert TELEGRAM_MAX_MSG == 4096


def test_ollama_config():
    from config import OLLAMA_BASE, DEFAULT_MODEL, OLLAMA_TIMEOUT_SEC
    assert OLLAMA_BASE.startswith("http")
    assert isinstance(DEFAULT_MODEL, str)
    assert OLLAMA_TIMEOUT_SEC > 0


def test_auth_config():
    from config import SESSION_TTL_SEC, LOGIN_MAX_FAILS, LOGIN_LOCK_SEC
    assert SESSION_TTL_SEC > 0
    assert LOGIN_MAX_FAILS > 0
    assert LOGIN_LOCK_SEC > 0


def test_context_config():
    from config import DEFAULT_CONTEXT_TURNS, DEFAULT_CONTEXT_TTL_SEC
    assert DEFAULT_CONTEXT_TURNS > 0
    assert DEFAULT_CONTEXT_TTL_SEC > 0


def test_tool_config():
    from config import (
        TOOL_SANDBOX_PATH, TOOL_SANDBOX_ENABLED, CODE_EXECUTION_TIMEOUT,
        TOOL_MAX_ITERATIONS, DUCKDUCKGO_MAX_RESULTS, MAX_FILE_READ_CHARS,
    )
    assert isinstance(TOOL_SANDBOX_PATH, str)
    assert isinstance(TOOL_SANDBOX_ENABLED, bool)
    assert CODE_EXECUTION_TIMEOUT > 0
    assert TOOL_MAX_ITERATIONS > 0
    assert DUCKDUCKGO_MAX_RESULTS > 0
    assert MAX_FILE_READ_CHARS > 0


def test_comfyui_config():
    from config import COMFY_BASE, COMFY_TIMEOUT_SEC, COMFY_OUTPUT_DIR, COMFY_STEPS, COMFY_CFG, COMFY_DENOISE
    assert COMFY_BASE.startswith("http")
    assert COMFY_TIMEOUT_SEC > 0
    assert isinstance(COMFY_OUTPUT_DIR, str)
    assert COMFY_STEPS > 0
    assert COMFY_CFG >= 0
    assert 0 <= COMFY_DENOISE <= 1.0


def test_streaming_config():
    from config import STREAMING_EDIT_INTERVAL, STREAMING_MIN_DELTA
    assert STREAMING_EDIT_INTERVAL > 0
    assert STREAMING_MIN_DELTA > 0


def test_default_model_params():
    from config import DEFAULT_MODEL_PARAMS
    required_keys = {"temperature", "top_p", "top_k", "num_ctx", "num_predict", "repeat_penalty", "seed", "keep_alive"}
    assert required_keys.issubset(DEFAULT_MODEL_PARAMS.keys())
    assert 0 <= DEFAULT_MODEL_PARAMS["temperature"] <= 2.0
    assert 0 <= DEFAULT_MODEL_PARAMS["top_p"] <= 1.0


def test_upload_temp_dir():
    from config import UPLOAD_TEMP_DIR
    assert isinstance(UPLOAD_TEMP_DIR, str)
    assert len(UPLOAD_TEMP_DIR) > 0
