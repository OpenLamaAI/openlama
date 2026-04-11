"""Telegram bot entry point."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import Application

from openlama.config import get_config
from openlama.database import get_admin_password_hash, init_db, set_setting
from openlama.auth import hash_password
from openlama.tools import init_tools
from openlama.channels.telegram.handlers import register_all_handlers, post_init
from openlama.channels.base import Channel
from openlama.logger import setup_logger, get_logger

logger = get_logger("telegram.bot")


def validate_env():
    token = get_config("telegram_bot_token")
    if not token:
        print()
        print("  openlama is not configured yet.")
        print("  Run 'openlama setup' first to complete initial setup.")
        print()
        raise SystemExit(1)


def setup_admin_password():
    """Initialize admin password hash from env on first run."""
    import os
    existing = get_admin_password_hash()
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    if not existing and admin_pw:
        set_setting("admin_password_hash", hash_password(admin_pw))
        logger.info("Admin password hash initialized from ADMIN_PASSWORD env var.")


class TelegramChannel(Channel):
    """Telegram bot channel."""

    def __init__(self):
        self._app: Application | None = None

    async def start(self):
        from openlama.config import DATA_DIR
        setup_logger(log_file=DATA_DIR / "openlama.log")

        validate_env()
        init_db()
        setup_admin_password()
        init_tools()

        token = get_config("telegram_bot_token")

        # Python 3.14 compat
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        self._app = Application.builder().token(token).post_init(post_init).build()
        register_all_handlers(self._app)
        logger.info("Telegram bot starting polling...")
        self._app.run_polling(allowed_updates=Update.ALL_TYPES)

    async def stop(self):
        if self._app:
            await self._app.stop()
            await self._app.shutdown()
            self._app = None


async def _check_ollama_update(app):
    """Check for Ollama updates on bot startup."""
    try:
        from openlama.ollama_client import check_ollama_update
        info = await check_ollama_update()
        if info["update_available"]:
            logger.warning(
                "Ollama update available: v%s → v%s. "
                "Run 'openlama doctor fix' or update Ollama manually.",
                info["current"], info["latest"],
            )
        else:
            logger.info("Ollama v%s (up to date)", info["current"])
    except Exception as e:
        logger.debug("Ollama version check skipped: %s", e)


async def _start_scheduler(app):
    """Start the cron scheduler and register Telegram as the output channel."""
    try:
        from openlama.core.scheduler import start_scheduler, set_channel_sender

        async def _telegram_sender(chat_id: int, text: str):
            """Send cron job results to Telegram chat with markdown formatting."""
            try:
                from openlama.utils.formatting import convert_markdown, split_message
                plain, entities = convert_markdown(text)
                parts = split_message(plain, entities)
                for chunk_text, chunk_ents in parts:
                    await app.bot.send_message(
                        chat_id=chat_id, text=chunk_text, entities=chunk_ents,
                    )
            except Exception:
                # Fallback: send as plain text
                try:
                    if len(text) > 4000:
                        text = text[:4000] + "\n\n... (truncated)"
                    await app.bot.send_message(chat_id=chat_id, text=text)
                except Exception as e:
                    logger.error("failed to send cron result to chat %d: %s", chat_id, e)

        set_channel_sender(_telegram_sender)
        start_scheduler()
    except Exception as e:
        logger.warning("Scheduler startup failed (non-fatal): %s", e)


async def _start_mcp_servers(app):
    """Start all configured MCP servers after bot init."""
    try:
        from openlama.core.mcp_client import start_all_servers, register_mcp_tools_to_registry
        await start_all_servers()
        register_mcp_tools_to_registry()
    except Exception as e:
        logger.warning("MCP server startup failed (non-fatal): %s", e)


async def _stop_mcp_servers(app):
    """Stop all MCP servers on bot shutdown."""
    try:
        from openlama.core.mcp_client import stop_all_servers
        await stop_all_servers()
    except Exception as e:
        logger.warning("MCP server shutdown error: %s", e)


def main():
    """Standalone entry point for running just the Telegram bot."""
    from openlama.config import DATA_DIR
    setup_logger(log_file=DATA_DIR / "openlama.log")

    validate_env()
    init_db()
    setup_admin_password()
    init_tools()

    token = get_config("telegram_bot_token")

    # Python 3.14 compat
    asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(token).post_init(post_init).build()
    register_all_handlers(app)

    # Post-init lifecycle hooks
    app.post_init = _chain_post_init(app.post_init, _check_ollama_update)
    app.post_init = _chain_post_init(app.post_init, _start_mcp_servers)
    app.post_init = _chain_post_init(app.post_init, _start_scheduler)
    app.post_shutdown = _stop_mcp_servers

    print()
    print("  ✓ openlama is running (Telegram bot)")
    print("    Press Ctrl+C to stop.")
    print()
    print("  Tips:")
    print("    openlama start -d    Run in background (daemon)")
    print("    openlama chat        Terminal chat mode")
    print()

    app.run_polling(allowed_updates=Update.ALL_TYPES)


def _chain_post_init(original, additional):
    """Chain two post_init callbacks."""
    async def chained(app):
        if original:
            await original(app)
        await additional(app)
    return chained


if __name__ == "__main__":
    main()
