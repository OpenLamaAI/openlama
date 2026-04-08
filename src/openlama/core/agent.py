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


async def _call_with_auto_trim(
    model: str, messages: list[dict], settings, tools, think: bool,
    uid: int, ctx_items: list[dict],
) -> dict:
    """Call Ollama with automatic context trimming on overflow.

    If the request exceeds num_ctx (400 error), progressively removes
    the oldest context messages and retries. If still failing after
    trimming, compresses remaining context and retries once more.
    """
    last_error = None
    for attempt in range(4):
        try:
            return await chat_with_ollama_full(
                model, messages, settings=settings, tools=tools, think=think,
            )
        except Exception as e:
            last_error = e
            err_str = str(e).lower()

            # Only retry on context-related 400 errors
            is_context_error = "400" in str(e) and any(
                kw in err_str for kw in ("context", "too long", "exceed", "token", "length")
            )

            if not is_context_error and "400" in str(e):
                # 400 but not context-related — might be malformed request.
                # Try once without tools (tools can cause 400 on some models)
                if tools and attempt == 0:
                    logger.warning("400 error, retrying without tools: %s", err_str[:200])
                    tools = None
                    continue
                raise

            if not is_context_error:
                raise

            system_msg = messages[0]
            user_msg = messages[-1]
            context_msgs = messages[1:-1]

            logger.warning(
                "Context overflow (attempt %d, %d context msgs). Trimming...",
                attempt + 1, len(context_msgs),
            )

            if len(context_msgs) <= 2:
                messages = [system_msg, user_msg]
                save_context(uid, [])
                continue

            half = max(2, len(context_msgs) // 2)
            context_msgs = context_msgs[half:]
            messages = [system_msg] + context_msgs + [user_msg]

            keep_turns = len(context_msgs) // 2
            if len(ctx_items) > keep_turns:
                ctx_items = ctx_items[-keep_turns:] if keep_turns > 0 else []
                save_context(uid, ctx_items)

    raise last_error or RuntimeError("Chat failed after retries")


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

    # Call model — auto-trim context on overflow (400 error)
    resp = await _call_with_auto_trim(model, messages, settings, tools, think, uid, ctx_items)

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

    # Save context (generous limit to avoid DB bloat while preserving detail)
    answer = content.strip() if content else ""
    ctx_entry = {"u": request.text[:10000], "a": answer[:10000]}
    ctx_items.append(ctx_entry)
    save_context(uid, ctx_items)

    # Build context bar using Ollama's actual token counts
    # prompt_tokens from the initial call = full context window usage
    # completion_tokens = tokens generated, which become part of next prompt
    base_prompt = resp.get("prompt_tokens", 0)
    base_completion = resp.get("completion_tokens", 0)
    context_used = base_prompt + base_completion if base_prompt > 0 else _estimate_messages_tokens(system_prompt, ctx_items)
    context_bar = build_context_bar(context_used, settings.num_ctx, len(ctx_items))
    total_req = usage.prompt_tokens + usage.completion_tokens
    if total_req > 0:
        context_bar += f"\n\U0001f4ac This request: {usage.prompt_tokens:,} in + {usage.completion_tokens:,} out = {total_req:,}"

    return ChatResponse(
        content=answer,
        images=image_paths,
        usage=usage,
        context_bar=context_bar,
    )
