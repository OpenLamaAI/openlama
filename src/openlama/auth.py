"""Authentication helpers – password hashing, session checks."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from openlama.database import UserState, get_user, is_authed, now_ts
from telegram import Update


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000
    )
    return f"pbkdf2_sha256$200000${salt}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds, salt, digest = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(rounds)
        )
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


async def require_auth(update: Update) -> UserState | None:
    """Return UserState if authenticated, else reply and return None."""
    if not update.effective_user:
        return None
    uid = update.effective_user.id
    user = get_user(uid)
    if not is_authed(user):
        target = update.message or (update.callback_query and update.callback_query.message)
        if update.message:
            await update.message.reply_text("Authentication required: /login")
        return None
    return user
