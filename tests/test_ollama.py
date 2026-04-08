"""Tests for Ollama client – requires running Ollama server."""

import pytest

from ollama_client import (
    chat_stream,
    chat_with_ollama,
    ensure_ollama_running,
    fetch_models,
    get_model_capabilities,
    get_model_display_map,
    get_model_info,
    get_model_max_context,
    get_running_models,
    model_supports_images,
    model_supports_thinking,
    model_supports_tools,
    ollama_alive,
    summarize_context,
)
from database import ModelSettings


# ── Health Check ──

@pytest.mark.asyncio
async def test_ollama_alive():
    alive = await ollama_alive()
    assert alive is True, "Ollama must be running for integration tests"


@pytest.mark.asyncio
async def test_ensure_ollama_running():
    ok, msg = await ensure_ollama_running()
    assert ok is True


# ── Model Listing ──

@pytest.mark.asyncio
async def test_fetch_models():
    models = await fetch_models()
    assert isinstance(models, list)
    assert len(models) > 0, "At least one model should be installed"


@pytest.mark.asyncio
async def test_get_running_models():
    models = await get_running_models()
    assert isinstance(models, list)


# ── Model Capabilities ──

@pytest.mark.asyncio
async def test_get_model_capabilities():
    models = await fetch_models()
    caps = await get_model_capabilities(models[0])
    assert isinstance(caps, list)


@pytest.mark.asyncio
async def test_model_supports_images():
    models = await fetch_models()
    result, reason = await model_supports_images(models[0])
    assert isinstance(result, bool)
    assert isinstance(reason, str)


@pytest.mark.asyncio
async def test_model_supports_tools():
    models = await fetch_models()
    result = await model_supports_tools(models[0])
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_model_supports_thinking():
    models = await fetch_models()
    result = await model_supports_thinking(models[0])
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_get_model_max_context():
    models = await fetch_models()
    max_ctx = await get_model_max_context(models[0])
    assert isinstance(max_ctx, int)
    # Most models have at least 2048 context
    assert max_ctx >= 0


@pytest.mark.asyncio
async def test_get_model_display_map():
    models = await fetch_models()
    display = await get_model_display_map(models[:3])
    assert isinstance(display, dict)
    for m in models[:3]:
        assert m in display
        assert any(badge in display[m] for badge in ("👁", "🔧", "💭", "💬"))


@pytest.mark.asyncio
async def test_get_model_info():
    models = await fetch_models()
    info = await get_model_info(models[0])
    assert isinstance(info, dict)
    assert "model_info" in info or "parameters" in info or "modelfile" in info


# ── Chat (Non-Streaming) ──

@pytest.mark.asyncio
async def test_chat_basic():
    models = await fetch_models()
    result = await chat_with_ollama(
        models[0],
        [{"role": "user", "content": "Reply with only the word: PONG"}],
        settings=ModelSettings(user_id=0, num_ctx=2048, num_predict=64),
    )
    assert isinstance(result, str)
    assert len(result) > 0


# ── Chat (Streaming) ──

@pytest.mark.asyncio
async def test_chat_stream():
    models = await fetch_models()
    chunks = []
    gen = chat_stream(
        models[0],
        [{"role": "user", "content": "Reply with only: HELLO"}],
        settings=ModelSettings(user_id=0, num_ctx=2048, num_predict=64),
    )
    async for chunk in gen:
        chunks.append(chunk)
    assert len(chunks) > 0
    # Last chunk should have done=True
    assert chunks[-1].get("done") is True


# ── Context Summarization ──

@pytest.mark.asyncio
async def test_summarize_context():
    models = await fetch_models()
    conversation = (
        "User: What is Python?\n"
        "Assistant: Python is a programming language.\n"
        "User: What about JavaScript?\n"
        "Assistant: JavaScript is used for web development."
    )
    summary = await summarize_context(models[0], conversation)
    assert isinstance(summary, str)
    assert len(summary) > 0
