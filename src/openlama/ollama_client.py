"""Ollama API client – chat, streaming, model management, tool support."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator, Optional

import httpx

from openlama.config import get_config, get_config_int, get_config_float, DEFAULT_MODEL_PARAMS
from openlama.database import ModelSettings, now_ts
from openlama.logger import get_logger

logger = get_logger(__name__)

# ── In-memory caches ─────────────────────────────────────

PULL_STATE: dict[int, dict] = {}
MODEL_CAPS_CACHE: dict[str, dict] = {}

# ── Shared httpx client ──────────────────────────────────

_shared_client: httpx.AsyncClient | None = None


def _get_client(timeout: float | httpx.Timeout = 30) -> httpx.AsyncClient:
    """Get or create a shared httpx client. Use as context manager for streaming."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=timeout)
    return _shared_client


async def _api_get(path: str, timeout: float = 10) -> httpx.Response:
    """GET request to Ollama API."""
    base = get_config("ollama_base")
    async with httpx.AsyncClient(timeout=timeout) as c:
        return await c.get(f"{base}{path}")


async def _api_post(path: str, json: dict, timeout: float | None = None) -> httpx.Response:
    """POST request to Ollama API."""
    base = get_config("ollama_base")
    t = timeout or get_config_int("ollama_timeout_sec", 120)
    async with httpx.AsyncClient(timeout=t) as c:
        return await c.post(f"{base}{path}", json=json)


# ── Health check ─────────────────────────────────────────

async def ollama_alive() -> bool:
    try:
        r = await _api_get("/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def start_ollama_service() -> tuple[bool, str]:
    """Start Ollama via the correct service manager. Sync function.

    Detection order:
      1. macOS + brew installed via brew → brew services start
      2. Linux + systemd → systemctl start
      3. Fallback → ollama serve (direct, for Termux / manual installs)

    Returns (started: bool, method: str).
    """
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    ollama_bin = shutil.which("ollama")
    # Fallback: check known homebrew paths when PATH is incomplete (SSH)
    if not ollama_bin:
        for p in ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama"]:
            if Path(p).exists():
                ollama_bin = p
                break
    if not ollama_bin:
        return False, "ollama not found"

    def _find_brew() -> str | None:
        b = shutil.which("brew")
        if b:
            return b
        for p in ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"]:
            if Path(p).exists():
                return p
        return None

    # macOS: check if installed via brew
    brew_bin = _find_brew() if sys.platform == "darwin" else None
    if brew_bin:
        try:
            result = subprocess.run(
                [brew_bin, "list", "ollama"], capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                subprocess.run(
                    [brew_bin, "services", "start", "ollama"],
                    capture_output=True, text=True, timeout=15,
                )
                return True, "brew"
        except Exception:
            pass

    # Linux: systemctl
    if shutil.which("systemctl"):
        try:
            subprocess.run(
                ["systemctl", "start", "ollama"],
                capture_output=True, text=True, timeout=15,
            )
            return True, "systemctl"
        except Exception:
            pass

    # Fallback: direct serve (Termux, manual install, etc.)
    try:
        popen_kw = {}
        if sys.platform == "win32":
            popen_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            [ollama_bin, "serve"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **popen_kw,
        )
        return True, "direct"
    except Exception as e:
        return False, f"failed: {e}"


async def ensure_ollama_running() -> tuple[bool, str]:
    """Check if Ollama is alive. If not, attempt to start it."""
    if await ollama_alive():
        return True, "alive"

    # Try to start
    started, method = start_ollama_service()
    if not started:
        return False, f"Ollama not reachable and could not start ({method})"

    # Wait for startup
    for _ in range(15):
        await asyncio.sleep(1)
        if await ollama_alive():
            logger.info("Ollama started via %s", method)
            return True, f"started ({method})"

    return False, f"Ollama started ({method}) but not responding"


async def get_ollama_version() -> str | None:
    """Get the running Ollama server version."""
    try:
        r = await _api_get("/api/version", timeout=5)
        if r.status_code == 200:
            return r.json().get("version")
    except Exception:
        pass
    return None


async def get_ollama_latest_version() -> str | None:
    """Fetch the latest Ollama release version from GitHub."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            r = await client.get(
                "https://api.github.com/repos/ollama/ollama/releases/latest",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if r.status_code == 200:
                tag = r.json().get("tag_name", "")
                return tag.lstrip("v")
    except Exception:
        pass
    return None


def _parse_version(v: str) -> tuple:
    """Parse version string into comparable tuple."""
    try:
        parts = v.split("-")[0].split(".")
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return (0,)


async def check_ollama_update() -> dict:
    """Check if Ollama needs updating.

    Returns: {"current": str, "latest": str, "update_available": bool}
    """
    current = await get_ollama_version()
    latest = await get_ollama_latest_version()

    if not current or not latest:
        return {"current": current or "unknown", "latest": latest or "unknown", "update_available": False}

    update_available = _parse_version(latest) > _parse_version(current)
    return {"current": current, "latest": latest, "update_available": update_available}


# ── Model listing ─────────────────────────────────────────

async def fetch_models() -> list[str]:
    r = await _api_get("/api/tags")
    r.raise_for_status()
    data = r.json()
    models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    models.sort()
    return models


list_models = fetch_models


async def fetch_models_detailed() -> list[dict]:
    r = await _api_get("/api/tags")
    r.raise_for_status()
    return r.json().get("models", [])


async def get_running_models() -> list[dict]:
    try:
        r = await _api_get("/api/ps", timeout=5)
        r.raise_for_status()
        return r.json().get("models", [])
    except Exception:
        return []


# ── Model capabilities ───────────────────────────────────

async def get_model_capabilities(model: str) -> list[str]:
    """Get model capabilities list (vision, tools, etc.)."""
    now = now_ts()
    ttl = get_config_int("model_vision_cache_ttl_sec", 3600)
    cached = MODEL_CAPS_CACHE.get(model)
    if cached and (now - cached.get("ts", 0)) <= ttl:
        return cached.get("caps", [])

    caps: list[str] = []
    try:
        r = await _api_post("/api/show", json={"name": model}, timeout=15)
        r.raise_for_status()
        data = r.json()

        raw_caps = data.get("capabilities")
        if isinstance(raw_caps, list):
            caps = [str(c).lower() for c in raw_caps]
        elif isinstance(raw_caps, dict):
            flat = json.dumps(raw_caps, ensure_ascii=False).lower()
            for kw in ("vision", "image", "multimodal", "tools", "thinking", "audio"):
                if kw in flat:
                    caps.append(kw)
    except Exception:
        pass

    MODEL_CAPS_CACHE[model] = {"caps": caps, "ts": now}
    return caps


async def model_supports_images(model: str) -> tuple[bool, str]:
    caps = await get_model_capabilities(model)
    if any(c in caps for c in ("vision", "image", "multimodal")):
        return True, "vision confirmed via capabilities"

    # Probe fallback
    ok, reason = await _probe_model_image_support(model)
    if ok:
        cached = MODEL_CAPS_CACHE.get(model, {"caps": [], "ts": now_ts()})
        cached["caps"] = list(set(cached.get("caps", []) + ["vision"]))
        MODEL_CAPS_CACHE[model] = cached
    return ok, reason


async def model_supports_tools(model: str) -> bool:
    caps = await get_model_capabilities(model)
    return "tools" in caps


async def model_supports_thinking(model: str) -> bool:
    caps = await get_model_capabilities(model)
    return "thinking" in caps


async def _probe_model_image_support(model: str) -> tuple[bool, str]:
    tiny_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5Y6xkAAAAASUVORK5CYII="
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Describe.", "images": [tiny_png_b64]}],
        "stream": False,
    }
    try:
        r = await _api_post("/api/chat", json=payload, timeout=15)
        if r.status_code >= 400:
            msg = r.text.lower()
            if any(k in msg for k in ("does not support", "not support", "vision", "image")):
                return False, "images not supported"
            return False, f"probe failed: http {r.status_code}"
        data = r.json()
        content = ((data.get("message") or {}).get("content") or "").strip()
        return (True, "probe success") if content else (False, "probe response empty")
    except Exception as e:
        return False, f"probe exception: {e}"


async def get_model_max_context(model: str) -> int:
    """Get model's maximum context length from Ollama model info."""
    try:
        info = await get_model_info(model)
        # Check model_info field (contains training parameters)
        model_info = info.get("model_info", {})
        for key, val in model_info.items():
            if "context_length" in key.lower() and isinstance(val, (int, float)):
                return int(val)
        # Fallback: check parameters string
        params_str = info.get("parameters", "")
        if params_str:
            for line in params_str.split("\n"):
                if "num_ctx" in line.lower():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try:
                            return int(parts[-1])
                        except ValueError:
                            pass
    except Exception:
        pass
    return 0  # Unknown


async def get_model_display_map(models: list[str]) -> dict[str, str]:
    display: dict[str, str] = {}
    for m in models:
        caps = await get_model_capabilities(m)
        badges = []
        if any(c in caps for c in ("vision", "image", "multimodal")):
            badges.append("\U0001f441")
        if "tools" in caps:
            badges.append("\U0001f527")
        if "thinking" in caps:
            badges.append("\U0001f4ad")
        if not badges:
            badges.append("\U0001f4ac")
        display[m] = f"{''.join(badges)} {m}"
    return display


# ── Chat ──────────────────────────────────────────────────

def _normalize_keep_alive(value: str) -> str:
    """Ensure keep_alive has a time unit. Ollama requires '60s', '5m', etc."""
    v = str(value).strip()
    if not v:
        return "30m"
    # Already has unit (s, m, h) or is "0"
    if v[-1] in ("s", "m", "h") or v == "0":
        return v
    # Pure number — treat as seconds
    try:
        int(v)
        return v + "s"
    except ValueError:
        return v


def _build_options(settings: ModelSettings) -> dict:
    opts: dict[str, Any] = {}
    defaults = DEFAULT_MODEL_PARAMS
    if settings.temperature != defaults["temperature"]:
        opts["temperature"] = settings.temperature
    if settings.top_p != defaults["top_p"]:
        opts["top_p"] = settings.top_p
    if settings.top_k != defaults["top_k"]:
        opts["top_k"] = settings.top_k
    if settings.num_ctx != defaults["num_ctx"]:
        opts["num_ctx"] = settings.num_ctx
    if settings.num_predict != defaults["num_predict"]:
        opts["num_predict"] = settings.num_predict
    if settings.repeat_penalty != defaults["repeat_penalty"]:
        opts["repeat_penalty"] = settings.repeat_penalty
    if settings.seed != defaults["seed"]:
        opts["seed"] = settings.seed
    opts.setdefault("num_ctx", settings.num_ctx)
    opts.setdefault("num_predict", settings.num_predict)
    return opts


def _build_chat_payload(
    model: str,
    messages: list[dict],
    *,
    stream: bool = False,
    images: Optional[list[str]] = None,
    settings: Optional[ModelSettings] = None,
    tools: Optional[list[dict]] = None,
    think: bool = False,
) -> dict:
    """Build Ollama chat API payload. Shared by all chat functions."""
    payload_messages = [dict(m) for m in messages]
    if images:
        for i in range(len(payload_messages) - 1, -1, -1):
            if payload_messages[i].get("role") == "user":
                payload_messages[i]["images"] = images
                break

    payload: dict[str, Any] = {"model": model, "messages": payload_messages, "stream": stream}
    if settings:
        opts = _build_options(settings)
        if opts:
            payload["options"] = opts
        if settings.keep_alive != DEFAULT_MODEL_PARAMS["keep_alive"]:
            payload["keep_alive"] = _normalize_keep_alive(settings.keep_alive)
    if tools:
        payload["tools"] = tools
    if think:
        payload["think"] = True
    return payload


async def chat_with_ollama(
    model: str,
    messages: list[dict],
    images: Optional[list[str]] = None,
    settings: Optional[ModelSettings] = None,
    tools: Optional[list[dict]] = None,
    think: bool = False,
) -> str:
    """Non-streaming chat. Returns response text."""
    payload = _build_chat_payload(model, messages, images=images, settings=settings, tools=tools, think=think)
    r = await _api_post("/api/chat", json=payload)
    r.raise_for_status()
    data = r.json()

    msg = data.get("message") or {}
    return msg.get("content", "").strip()


async def chat_with_ollama_full(
    model: str,
    messages: list[dict],
    settings: Optional[ModelSettings] = None,
    tools: Optional[list[dict]] = None,
    think: bool = False,
) -> dict:
    """Non-streaming chat returning full message (content + tool_calls).

    Returns: {"content": str, "tool_calls": list, "prompt_tokens": int, "completion_tokens": int}
    """
    payload = _build_chat_payload(model, messages, settings=settings, tools=tools, think=think)
    r = await _api_post("/api/chat", json=payload)
    if r.status_code != 200:
        error_body = r.text[:500]
        logger.error("Ollama API error %d: %s", r.status_code, error_body)
        r.raise_for_status()
    data = r.json()

    msg = data.get("message") or {}
    return {
        "content": msg.get("content", "").strip(),
        "tool_calls": msg.get("tool_calls", []),
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "completion_tokens": data.get("eval_count", 0),
    }


async def chat_stream(
    model: str,
    messages: list[dict],
    images: Optional[list[str]] = None,
    settings: Optional[ModelSettings] = None,
    tools: Optional[list[dict]] = None,
    think: bool = False,
) -> AsyncGenerator[dict, None]:
    """Streaming chat. Yields parsed JSON chunks."""
    payload = _build_chat_payload(model, messages, stream=True, images=images, settings=settings, tools=tools, think=think)

    timeout = httpx.Timeout(connect=10, read=None, write=30, pool=30)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", f"{get_config('ollama_base')}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue


# ── Model management ──────────────────────────────────────

async def get_model_info(model: str) -> dict:
    r = await _api_post("/api/show", json={"name": model}, timeout=15)
    r.raise_for_status()
    return r.json()


async def copy_model(source: str, dest: str):
    r = await _api_post("/api/copy", json={"source": source, "destination": dest}, timeout=30)
    r.raise_for_status()


async def delete_model(model: str):
    base = get_config("ollama_base")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request("DELETE", f"{base}/api/delete", json={"name": model})
        if r.status_code == 405:
            r = await c.post(f"{base}/api/delete", json={"name": model})
        r.raise_for_status()


async def unload_model(model: str):
    try:
        await _api_post("/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
    except Exception:
        pass


# ── Pull (streaming progress) ────────────────────────────

def get_pull_state(uid: int) -> Optional[dict]:
    return PULL_STATE.get(uid)


def set_pull_state(uid: int, **kwargs):
    cur = PULL_STATE.get(uid, {})
    cur.update(kwargs)
    cur["updated_at"] = now_ts()
    PULL_STATE[uid] = cur


async def pull_model_stream(uid: int, model: str):
    set_pull_state(uid, status="running", model=model, progress=0, detail="starting", started_at=now_ts())
    try:
        ok, msg = await ensure_ollama_running()
        if not ok:
            logger.error("Ollama not reachable for pull: %s", msg)
            set_pull_state(uid, status="failed", detail=f"Ollama connection failed: {msg}")
            return

        timeout = httpx.Timeout(connect=10, read=None, write=30, pool=30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{get_config('ollama_base')}/api/pull", json={"name": model, "stream": True}) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue

                    if obj.get("error"):
                        set_pull_state(uid, status="failed", detail=str(obj.get("error")))
                        return

                    status = obj.get("status") or "in progress"
                    total = obj.get("total")
                    completed = obj.get("completed")
                    progress = None
                    if isinstance(total, int) and total > 0 and isinstance(completed, int):
                        progress = max(0, min(100, int((completed / total) * 100)))

                    set_pull_state(
                        uid,
                        status="running",
                        detail=status,
                        progress=progress if progress is not None else PULL_STATE.get(uid, {}).get("progress", 0),
                    )

                    if obj.get("status") == "success":
                        set_pull_state(uid, status="done", detail="installation complete", progress=100, finished_at=now_ts())
                        return

        st = get_pull_state(uid) or {}
        if st.get("status") == "running":
            set_pull_state(uid, status="done", detail="installation complete", progress=100, finished_at=now_ts())
    except Exception as e:
        logger.error("pull_model_stream error: %s", e)
        set_pull_state(uid, status="failed", detail=str(e)[:300])


# ── Context summarization ─────────────────────────────────

_SUMMARIZE_PROMPT = (
    "Summarize the conversation concisely.\n"
    "MUST PRESERVE:\n"
    "- Active tasks and their current status\n"
    "- The last thing the user requested and what was being done\n"
    "- Decisions made and their rationale\n"
    "- File paths, URLs, IDs, and identifiers exactly as written\n"
    "- Any commitments or follow-ups promised\n"
    "PRIORITIZE recent context over older history.\n"
    "Keep the summary under 800 characters."
)


async def summarize_context(model: str, conversation_text: str) -> str:
    """Summarize a conversation for context compression."""
    messages = [
        {"role": "system", "content": _SUMMARIZE_PROMPT},
        {"role": "user", "content": conversation_text},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": 1024, "temperature": 0.3},
    }
    r = await _api_post("/api/chat", json=payload)
    r.raise_for_status()
    data = r.json()
    return (data.get("message") or {}).get("content", "").strip()
