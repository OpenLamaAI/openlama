"""Channel-independent chat engine."""
from __future__ import annotations

import base64
import json
import re

from openlama.core.types import ChatRequest, ChatResponse, TokenUsage
from openlama.core.context import maybe_compress, _estimate_messages_tokens, build_context_bar
from openlama.core.prompt_builder import build_full_system_prompt, is_profile_setup_done
from openlama.core.skills import match_skill, get_skill_prompt
from openlama.database import (
    get_user, get_model_settings, load_context, save_context,
)
from openlama.ollama_client import (
    chat_with_ollama_full, ensure_ollama_running,
    model_supports_thinking,
)
from openlama.tools import execute_tool, format_tools_for_ollama
from openlama.config import get_config_int
from openlama.logger import get_logger

logger = get_logger("agent")

PROFILE_QUESTIONS = {
    "users": (
        "Hello! First, tell me about yourself.\n"
        "Feel free to share your name, occupation, tech stack, and areas of interest "
        "so I can provide more personalized assistance."
    ),
    "soul": (
        "Now let's set up my role.\n"
        "1. What should you call me? (e.g., Toby, AI, etc.)\n"
        "2. What should I call you?\n"
        "3. What role would you like me to play?\n"
        "4. What response style do you prefer? (e.g., concise, detailed)"
    ),
}


async def handle_tool_calls(
    uid: int,
    model: str,
    messages: list[dict],
    tool_calls: list[dict],
    settings,
    think: bool,
    tools: list[dict] | None = None,
    on_progress=None,
) -> tuple[str, list[str], TokenUsage]:
    """Multi-turn tool loop. Returns (answer, image_paths, usage)."""
    max_iter = get_config_int("tool_max_iterations", 20)
    total_usage = TokenUsage()
    image_paths: list[str] = []
    pending = tool_calls

    for iteration in range(max_iter):
        if not pending:
            break

        round_tool_names = []
        for tc in pending:
            fn = tc.get("function", {})
            name = fn.get("name", "unknown")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            round_tool_names.append(name)
            if on_progress:
                await on_progress(f"\U0001f527 Running tool... (round {iteration + 1}, {name})")

            result = await execute_tool(name, args, uid)

            # Extract image paths
            for m in re.finditer(r"\[IMAGE:(.*?)]", result):
                image_paths.append(m.group(1))
            result = re.sub(r"\[IMAGE:.*?]", "", result).strip()

            messages.append({"role": "assistant", "content": "", "tool_calls": [tc]})
            messages.append({"role": "tool", "content": result})

        logger.info("round %d: tools=%s", iteration + 1, round_tool_names)

        is_last = iteration >= max_iter - 1
        call_tools = tools if not is_last else None
        if is_last:
            messages.append({
                "role": "system",
                "content": "Synthesize all tool results collected so far and compose a final answer to the user's question."
            })

        resp = await chat_with_ollama_full(model, messages, settings=settings, tools=call_tools, think=think)
        total_usage.prompt_tokens += resp.get("prompt_tokens", 0)
        total_usage.completion_tokens += resp.get("completion_tokens", 0)

        new_tool_calls = resp.get("tool_calls", [])
        content = resp.get("content", "")

        if new_tool_calls and not is_last:
            pending = new_tool_calls
            if content:
                messages.append({"role": "assistant", "content": content})
            continue

        if content:
            return content, image_paths, total_usage

    return "Maximum tool call iterations reached.", image_paths, total_usage


async def chat(request: ChatRequest) -> ChatResponse:
    """Main chat entry point — channel independent."""
    uid = request.user_id
    user = get_user(uid)
    model = user.selected_model
    if not model:
        return ChatResponse(content="No model selected. Please select a model with /models.")

    ok, msg = await ensure_ollama_running()
    if not ok:
        return ChatResponse(content=f"Ollama connection failed: {msg}")

    settings = get_model_settings(uid, model)
    think = bool(user.think_mode) and await model_supports_thinking(model)

    # Build system prompt with current date
    system_prompt = build_full_system_prompt()
    from datetime import datetime, timezone, timedelta
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    system_prompt += f"\n\nCurrent date/time: {utc_now}"

    # Load context
    ctx_items = load_context(uid)
    ctx_items, summary = await maybe_compress(
        uid, model, ctx_items,
        num_ctx=settings.num_ctx,
        system_prompt=system_prompt,
        user_text=request.text,
    )

    # Match skill and inject into system prompt
    matched = match_skill(request.text)
    if matched:
        skill_body = get_skill_prompt(matched["name"])
        if skill_body:
            system_prompt += f"\n\n[Skill activated: {matched['name']}]\n{skill_body}"
            logger.info("skill matched: %s", matched["name"])

    # Build messages
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if summary:
        messages.append({"role": "user", "content": "[Context summary]"})
        messages.append({"role": "assistant", "content": summary})
    for item in ctx_items:
        messages.append({"role": "user", "content": item.get("u", "")})
        messages.append({"role": "assistant", "content": item.get("a", "")})

    user_msg: dict = {"role": "user", "content": request.text}
    if request.images:
        user_msg["images"] = [base64.b64encode(img).decode() for img in request.images]
    messages.append(user_msg)

    # Get tools
    tools = format_tools_for_ollama(admin=True)

    # Call model
    resp = await chat_with_ollama_full(model, messages, settings=settings, tools=tools, think=think)

    usage = TokenUsage(
        prompt_tokens=resp.get("prompt_tokens", 0),
        completion_tokens=resp.get("completion_tokens", 0),
    )
    content = resp.get("content", "")
    tool_calls = resp.get("tool_calls", [])
    image_paths: list[str] = []

    if tool_calls:
        content, image_paths, tool_usage = await handle_tool_calls(
            uid, model, messages, tool_calls, settings, think, tools=tools,
        )
        usage.prompt_tokens += tool_usage.prompt_tokens
        usage.completion_tokens += tool_usage.completion_tokens

    # Save context
    answer = content.strip() if content else ""
    ctx_entry = {"u": request.text[:2000], "a": answer[:2000]}
    ctx_items.append(ctx_entry)
    save_context(uid, ctx_items)

    # Build context bar
    est_tokens = _estimate_messages_tokens(system_prompt, ctx_items)
    context_bar = build_context_bar(est_tokens, settings.num_ctx, len(ctx_items))
    total_req = usage.prompt_tokens + usage.completion_tokens
    if total_req > 0:
        context_bar += f"\n\U0001f4ac This request: {usage.prompt_tokens:,} in + {usage.completion_tokens:,} out = {total_req:,}"

    return ChatResponse(
        content=answer,
        images=image_paths,
        usage=usage,
        context_bar=context_bar,
    )
