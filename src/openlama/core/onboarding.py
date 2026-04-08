"""Onboarding logic — shared between CLI and Telegram channels."""
from __future__ import annotations

from openlama.logger import get_logger

logger = get_logger("onboarding")

LANGUAGES = [
    ("en", "English"),
    ("ko", "Korean"),
    ("ja", "Japanese"),
    ("zh", "Chinese"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
    ("ar", "Arabic"),
]

REFINE_USERS_TEMPLATE = """You are a system prompt engineer. Refine the following raw user profile into a structured, concise profile in English. Max 200 characters. Keep only facts. No fluff.

Template:
# User Profile
- Name: ...
- Role: ...
- Stack: ...
- Language: ...
- Interests: ...

Raw input:
{raw_input}

User's primary language: {language}

Output ONLY the refined markdown. No explanation."""

REFINE_SOUL_TEMPLATE = """You are a system prompt engineer. Refine the following raw agent identity into a structured, concise identity in English. Max 200 characters. Keep only essential directives. No fluff.

Template:
# Agent Identity
- Name: ...
- Calls user: ...
- Role: ...
- Style: ...

Raw input:
{raw_input}

Output ONLY the refined markdown. No explanation."""


async def refine_prompt_with_ai(model: str, raw_input: str, template: str, **kwargs) -> str:
    """Use Ollama to refine a raw user input into a structured prompt."""
    from openlama.ollama_client import chat_with_ollama

    prompt = template.format(raw_input=raw_input, **kwargs)
    messages = [
        {"role": "system", "content": "You are a concise system prompt engineer. Output only the requested format."},
        {"role": "user", "content": prompt},
    ]

    try:
        result = await chat_with_ollama(model, messages)
        result = result.strip()
        if result and len(result) > 20:
            logger.info("refined prompt: %d chars -> %d chars", len(raw_input), len(result))
            return result
    except Exception as e:
        logger.warning("AI refinement failed, using raw input: %s", e)

    return ""


async def refine_users_prompt(model: str, raw_input: str, language: str) -> str:
    return await refine_prompt_with_ai(
        model, raw_input, REFINE_USERS_TEMPLATE, language=language,
    )


async def refine_soul_prompt(model: str, raw_input: str) -> str:
    return await refine_prompt_with_ai(
        model, raw_input, REFINE_SOUL_TEMPLATE,
    )


async def check_model_available() -> tuple[bool, str, list[str]]:
    """Check if Ollama is running and has models.

    Returns: (ok, selected_model, available_models)
    """
    from openlama.ollama_client import ollama_alive, list_models
    from openlama.config import get_config

    if not await ollama_alive():
        return False, "", []

    models = await list_models()
    if not models:
        return False, "", []

    default = get_config("default_model")
    selected = default if default in models else models[0]
    return True, selected, models
