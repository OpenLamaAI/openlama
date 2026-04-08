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
MODEL_VISION_CACHE: dict[str, dict] = {}
MODEL_CAPS_CACHE: dict[str, dict] = {}  # {model: {"caps": [...], "ts": int}}


# ── Health check ─────────────────────────────────────────

async def ollama_alive() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{get_config('ollama_base')}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def ensure_ollama_running() -> tuple[bool, str]:
    if await ollama_alive():
        return True, "alive"
    return False, "Ollama not reachable"


async def get_ollama_version() -> str | None:
    """Get the running Ollama server version."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{get_config('ollama_base')}/api/version")
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
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{get_config('ollama_base')}/api/tags")
        r.raise_for_status()
        data = r.json()
    models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    models.sort()
    return models


# Alias so callers can use either name
list_models = fetch_models


async def fetch_models_detailed() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{get_config('ollama_base')}/api/tags")
        r.raise_for_status()
        data = r.json()
    return data.get("models", [])


async def get_running_models() -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{get_config('ollama_base')}/api/ps")
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
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{get_config('ollama_base')}/api/show", json={"name": model})
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
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{get_config('ollama_base')}/api/chat", json=payload)
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
    # Always include num_ctx and num_predict for explicit control
    opts.setdefault("num_ctx", settings.num_ctx)
    opts.setdefault("num_predict", settings.num_predict)
    return opts


async def chat_with_ollama(
    model: str,
    messages: list[dict],
    images: Optional[list[str]] = None,
    settings: Optional[ModelSettings] = None,
    tools: Optional[list[dict]] = None,
    think: bool = False,
) -> str:
    """Non-streaming chat. Returns response text."""
    payload_messages = [dict(m) for m in messages]
    if images:
        for i in range(len(payload_messages) - 1, -1, -1):
            if payload_messages[i].get("role") == "user":
                payload_messages[i]["images"] = images
                break

    payload: dict[str, Any] = {"model": model, "messages": payload_messages, "stream": False}
    if settings:
        opts = _build_options(settings)
        if opts:
            payload["options"] = opts
        if settings.keep_alive != DEFAULT_MODEL_PARAMS["keep_alive"]:
            payload["keep_alive"] = settings.keep_alive
    if tools:
        payload["tools"] = tools
    if think:
        payload["think"] = True

    timeout_sec = get_config_int("ollama_timeout_sec", 120)
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        r = await client.post(f"{get_config('ollama_base')}/api/chat", json=payload)
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
    payload_messages = [dict(m) for m in messages]
    payload: dict[str, Any] = {"model": model, "messages": payload_messages, "stream": False}
    if settings:
        opts = _build_options(settings)
        if opts:
            payload["options"] = opts
        if settings.keep_alive != DEFAULT_MODEL_PARAMS["keep_alive"]:
            payload["keep_alive"] = settings.keep_alive
    if tools:
        payload["tools"] = tools
    if think:
        payload["think"] = True

    timeout_sec = get_config_int("ollama_timeout_sec", 120)
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        r = await client.post(f"{get_config('ollama_base')}/api/chat", json=payload)
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
    payload_messages = [dict(m) for m in messages]
    if images:
        for i in range(len(payload_messages) - 1, -1, -1):
            if payload_messages[i].get("role") == "user":
                payload_messages[i]["images"] = images
                break

    payload: dict[str, Any] = {"model": model, "messages": payload_messages, "stream": True}
    if settings:
        opts = _build_options(settings)
        if opts:
            payload["options"] = opts
        if settings.keep_alive != DEFAULT_MODEL_PARAMS["keep_alive"]:
            payload["keep_alive"] = settings.keep_alive
    if tools:
        payload["tools"] = tools
    if think:
        payload["think"] = True

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
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{get_config('ollama_base')}/api/show", json={"name": model})
        r.raise_for_status()
        return r.json()


async def copy_model(source: str, dest: str):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{get_config('ollama_base')}/api/copy", json={"source": source, "destination": dest})
        r.raise_for_status()


async def delete_model(model: str):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request("DELETE", f"{get_config('ollama_base')}/api/delete", json={"name": model})
        if r.status_code == 405:
            r = await client.post(f"{get_config('ollama_base')}/api/delete", json={"name": model})
        r.raise_for_status()


async def unload_model(model: str):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{get_config('ollama_base')}/api/generate",
                json={"model": model, "keep_alive": 0},
            )
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

async def summarize_context(model: str, conversation_text: str) -> str:
    """Summarize a conversation for context compression."""
    messages = [
        {"role": "system", "content": "Summarize the given conversation concisely, keeping only key points. Preserve important facts, decisions, code, and instructions. Keep the summary under 300 characters."},
        {"role": "user", "content": conversation_text},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": 512, "temperature": 0.3},
    }
    timeout_sec = get_config_int("ollama_timeout_sec", 120)
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        r = await client.post(f"{get_config('ollama_base')}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
    return (data.get("message") or {}).get("content", "").strip()
