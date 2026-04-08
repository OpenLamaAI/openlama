"""Configuration — DB-first with environment variable fallback."""
import os
import sys
from pathlib import Path

# ── Platform detection ────────────────────────────────────
TERMUX = os.environ.get("TERMUX_VERSION") is not None
IS_ANDROID = sys.platform == "linux" and TERMUX
IS_MOBILE = IS_ANDROID  # iOS: future addition

# Data directory (only hardcoded path)
DATA_DIR = Path(os.environ.get("OPENLAMA_DATA_DIR", str(Path.home() / ".config" / "openlama")))

# Telegram constant (not configurable)
TELEGRAM_MAX_MSG = 4096
MODEL_PAGE_SIZE = 8

# Default model parameters
DEFAULT_MODEL_PARAMS = {
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 64,
    "num_ctx": 8192,
    "num_predict": 4096,
    "repeat_penalty": 1.0,
    "seed": 0,
    "keep_alive": "30m",
}

# Default system prompt (used until SYSTEM.md is created)
DEFAULT_SYSTEM_PROMPT = "Respond concisely and clearly."

# Environment variable → DB key mapping (for backward compat)
_ENV_MAP = {
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "admin_password_hash": None,  # DB only
    "ollama_base": "OLLAMA_BASE",
    "default_model": "DEFAULT_MODEL",
    "ollama_timeout_sec": "OLLAMA_TIMEOUT_SEC",
    "ollama_startup_wait_sec": "OLLAMA_STARTUP_WAIT_SEC",
    "session_ttl_sec": "SESSION_TTL_SEC",
    "login_max_fails": "LOGIN_MAX_FAILS",
    "login_lock_sec": "LOGIN_LOCK_SEC",
    "streaming_edit_interval": "STREAMING_EDIT_INTERVAL",
    "streaming_min_delta": "STREAMING_MIN_DELTA",
    "tool_sandbox_path": "TOOL_SANDBOX_PATH",
    "tool_sandbox_enabled": "TOOL_SANDBOX_ENABLED",
    "tool_max_iterations": "TOOL_MAX_ITERATIONS",
    "code_execution_timeout": "CODE_EXECUTION_TIMEOUT",
    "duckduckgo_max_results": "DUCKDUCKGO_MAX_RESULTS",
    "comfy_base": "COMFY_BASE",
    "comfy_timeout_sec": "COMFY_TIMEOUT_SEC",
    "comfy_output_dir": "COMFY_OUTPUT_DIR",
    "comfy_steps": "COMFY_STEPS",
    "comfy_cfg": "COMFY_CFG",
    "comfy_denoise": "COMFY_DENOISE",
    "upload_temp_dir": "UPLOAD_TEMP_DIR",
    "max_file_read_chars": "MAX_FILE_READ_CHARS",
    "model_vision_cache_ttl_sec": "MODEL_VISION_CACHE_TTL_SEC",
    "context_compress_threshold": None,
    "memory_max_items": None,
    "prompts_dir": None,
}

# Defaults for each config key
_DEFAULTS = {
    "telegram_bot_token": "",
    "ollama_base": "http://127.0.0.1:11434",
    "default_model": "",
    "ollama_timeout_sec": "120",
    "ollama_startup_wait_sec": "30",
    "session_ttl_sec": str(24 * 60 * 60),
    "login_max_fails": "5",
    "login_lock_sec": "600",
    "streaming_edit_interval": "1.5",
    "streaming_min_delta": "20",
    "tool_sandbox_path": str(Path.home() / "workspace" / "sandbox"),
    "tool_sandbox_enabled": "true",
    "tool_max_iterations": "20",
    "code_execution_timeout": "30",
    "duckduckgo_max_results": "5",
    "comfy_base": "http://127.0.0.1:8184",
    "comfy_timeout_sec": "300",
    "comfy_output_dir": str(Path.home() / "Documents" / "ComfyUI" / "output"),
    "comfy_steps": "4",
    "comfy_cfg": "1.0",
    "comfy_denoise": "1.0",
    "comfy_enabled": "false",
    "upload_temp_dir": str(DATA_DIR / "tmp_uploads"),
    "max_file_read_chars": "50000",
    "model_vision_cache_ttl_sec": "3600",
    "context_compress_threshold": "0.7",
    "memory_max_items": "50",
    "prompts_dir": str(DATA_DIR / "prompts"),
    "show_token_stats": "true",
    "comfy_start_cmd": "",
    "comfy_auto_stop": "true",
    "comfy_stop_delay_sec": "30",
    "comfy_workflow_txt2img": "txt2img_default",
    "comfy_workflow_img2img": "img2img_default",
}

# ── Mobile (Termux) defaults override ─────────────────────
if TERMUX:
    _DEFAULTS["tool_sandbox_path"] = str(DATA_DIR / "sandbox")
    _DEFAULTS["comfy_output_dir"] = str(DATA_DIR / "output")
    _DEFAULTS["comfy_enabled"] = "false"
    _DEFAULTS["ollama_timeout_sec"] = "180"


def get_config(key: str, default: str | None = None) -> str:
    """Get config value: DB first, then env var, then default."""
    # Try DB first (lazy import to avoid circular)
    try:
        from openlama.database import get_setting
        val = get_setting(key)
        if val is not None:
            return val
    except Exception:
        pass

    # Try environment variable
    env_key = _ENV_MAP.get(key)
    if env_key:
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return env_val

    # Built-in default first, then caller-provided default
    builtin = _DEFAULTS.get(key)
    if builtin is not None:
        return builtin
    if default is not None:
        return default
    return ""


def get_config_int(key: str, default: int = 0) -> int:
    return int(get_config(key, str(default)))

def get_config_float(key: str, default: float = 0.0) -> float:
    return float(get_config(key, str(default)))

def get_config_bool(key: str, default: bool = False) -> bool:
    return get_config(key, str(default)).lower() in ("true", "1", "yes")


def is_ollama_remote() -> bool:
    """Check if ollama_base points to a non-localhost server."""
    base = get_config("ollama_base")
    return not any(h in base for h in ("127.0.0.1", "localhost", "0.0.0.0"))
