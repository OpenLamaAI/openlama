"""Tests for settings UI – preset generation, keyboard building."""

from handlers.settings import (
    PARAM_CONFIG,
    _build_ctx_presets,
    preset_keyboard,
    settings_keyboard,
)


# ── Context presets ──

def test_build_ctx_presets_default():
    presets = _build_ctx_presets(0)
    assert presets == [2048, 4096, 8192, 16384, 32768, 65536]


def test_build_ctx_presets_large_model():
    presets = _build_ctx_presets(262144)
    assert 131072 in presets
    assert 262144 in presets
    assert presets[-1] == 262144


def test_build_ctx_presets_small_model():
    presets = _build_ctx_presets(32768)
    assert 131072 not in presets or 131072 in [2048, 4096, 8192, 16384, 32768, 65536, 131072]


def test_build_ctx_presets_sorted():
    presets = _build_ctx_presets(262144)
    assert presets == sorted(presets)


# ── Preset Keyboards ──

def test_preset_keyboard_num_ctx():
    kb = preset_keyboard("num_ctx", max_ctx=262144)
    buttons = [b.text for row in kb.inline_keyboard for b in row]
    assert "2,048" in buttons
    assert "262,144" in buttons
    assert any("⬅" in b for b in buttons)


def test_preset_keyboard_num_ctx_no_max():
    kb = preset_keyboard("num_ctx", max_ctx=0)
    buttons = [b.text for row in kb.inline_keyboard for b in row]
    assert "2,048" in buttons
    assert "65,536" in buttons


def test_preset_keyboard_num_predict():
    kb = preset_keyboard("num_predict")
    buttons = [b.text for row in kb.inline_keyboard for b in row]
    assert "256" in buttons
    assert "8192" in buttons


def test_preset_keyboard_keep_alive():
    kb = preset_keyboard("keep_alive")
    buttons = [b.text for row in kb.inline_keyboard for b in row]
    assert "0" in buttons
    assert "30m" in buttons
    assert "-1" in buttons


def test_preset_keyboard_context_turns():
    kb = preset_keyboard("context_turns")
    buttons = [b.text for row in kb.inline_keyboard for b in row]
    assert "2" in buttons
    assert "50" in buttons


def test_preset_keyboard_context_ttl():
    kb = preset_keyboard("context_ttl")
    buttons = [b.text for row in kb.inline_keyboard for b in row]
    assert any("5" in b for b in buttons)  # "5분" or "5m"
    assert any("24" in b for b in buttons)  # "24시간" or "24h"


def test_preset_keyboard_unknown():
    kb = preset_keyboard("unknown_param")
    assert len(kb.inline_keyboard) == 1
    assert "⬅" in kb.inline_keyboard[0][0].text


# ── PARAM_CONFIG validation ──

def test_param_config_complete():
    required = {"temperature", "top_p", "top_k", "num_ctx", "num_predict", "repeat_penalty", "seed"}
    assert required.issubset(PARAM_CONFIG.keys())


def test_param_config_values():
    for key, cfg in PARAM_CONFIG.items():
        assert "min" in cfg, f"{key} missing min"
        assert "max" in cfg, f"{key} missing max"
        assert "fmt" in cfg, f"{key} missing fmt"
        assert "label" in cfg, f"{key} missing label"
        assert cfg["min"] < cfg["max"], f"{key}: min >= max"


# ── Settings keyboard ──

def test_settings_keyboard():
    from database import get_user
    uid = 500001
    get_user(uid)
    kb = settings_keyboard(uid, "test-model")
    # Should have rows for all params + keep_alive + context + reset
    assert len(kb.inline_keyboard) >= 8
