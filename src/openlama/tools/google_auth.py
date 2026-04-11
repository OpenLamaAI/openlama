"""Google OAuth2 authentication and token management tool."""

from __future__ import annotations

import json
import asyncio
from pathlib import Path

from openlama.tools.registry import register_tool
from openlama.config import get_config, DATA_DIR
from openlama.crypto import encrypt, decrypt
from openlama.logger import get_logger

logger = get_logger("google_auth")

# All scopes we request (covers all Google services)
ALL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/contacts.other.readonly",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/keep",
    "https://www.googleapis.com/auth/chat.spaces",
    "https://www.googleapis.com/auth/chat.messages",
    "https://www.googleapis.com/auth/chat.memberships",
    "https://www.googleapis.com/auth/script.projects",
    "https://www.googleapis.com/auth/script.processes",
]

_SERVICE_SCOPE_MAP = {
    "gmail": [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.settings.basic",
    ],
    "calendar": ["https://www.googleapis.com/auth/calendar"],
    "drive": ["https://www.googleapis.com/auth/drive"],
    "docs": [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/documents",
    ],
    "sheets": [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ],
    "slides": [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/presentations",
    ],
    "contacts": [
        "https://www.googleapis.com/auth/contacts",
        "https://www.googleapis.com/auth/contacts.other.readonly",
    ],
    "tasks": ["https://www.googleapis.com/auth/tasks"],
    "forms": [
        "https://www.googleapis.com/auth/forms.body",
        "https://www.googleapis.com/auth/forms.responses.readonly",
    ],
    "keep": ["https://www.googleapis.com/auth/keep"],
    "chat": [
        "https://www.googleapis.com/auth/chat.spaces",
        "https://www.googleapis.com/auth/chat.messages",
        "https://www.googleapis.com/auth/chat.memberships",
    ],
    "appscript": [
        "https://www.googleapis.com/auth/script.projects",
        "https://www.googleapis.com/auth/script.processes",
    ],
}


def _get_credentials_json() -> dict | None:
    """Load OAuth client credentials from DB (encrypted)."""
    from openlama.database import get_setting
    enc = get_setting("google_credentials_enc")
    if not enc:
        return None
    try:
        return json.loads(decrypt(enc))
    except Exception:
        return None


def _get_token_json() -> dict | None:
    """Load OAuth token from DB (encrypted)."""
    from openlama.database import get_setting
    enc = get_setting("google_token_enc")
    if not enc:
        return None
    try:
        return json.loads(decrypt(enc))
    except Exception:
        return None


def _save_token(creds) -> None:
    """Save google.oauth2.credentials.Credentials to DB encrypted."""
    from openlama.database import set_setting
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or []),
    }
    set_setting("google_token_enc", encrypt(json.dumps(token_data)))
    # Save email for display
    try:
        from googleapiclient.discovery import build
        svc = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = svc.userinfo().get().execute()
        email = info.get("email", "")
        if email:
            set_setting("google_account_email", email)
    except Exception:
        pass


def get_google_creds():
    """Get valid Google credentials, refreshing if needed. Returns None if not configured."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_data = _get_token_json()
    if not token_data:
        return None

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes"),
    )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                _save_token(creds)
            except Exception as e:
                logger.error("Token refresh failed: %s", e)
                return None
        else:
            return None

    return creds


def build_service(api: str, version: str):
    """Build a Google API service client. Raises RuntimeError if not authenticated."""
    from googleapiclient.discovery import build
    creds = get_google_creds()
    if not creds:
        raise RuntimeError(
            "Google not authenticated. Run 'openlama google auth' or re-run 'openlama setup' to configure Google integration."
        )
    return build(api, version, credentials=creds, cache_discovery=False)


# ── Tool actions ─────────────────────────────────────

async def _action_status(args: dict) -> str:
    """Check Google authentication status."""
    from openlama.database import get_setting
    enabled = get_config("google_enabled")
    if enabled.lower() not in ("true", "1", "yes"):
        return "Google integration is disabled. Run 'openlama setup' to enable."

    email = get_setting("google_account_email") or "unknown"
    creds = get_google_creds()
    if not creds:
        return f"Google integration enabled but not authenticated. Run 'openlama google auth'."

    # Check which services are accessible
    token_data = _get_token_json()
    scopes = token_data.get("scopes", []) if token_data else []
    services = []
    for svc, svc_scopes in _SERVICE_SCOPE_MAP.items():
        if all(s in scopes for s in svc_scopes):
            services.append(svc)

    return (
        f"Authenticated as: {email}\n"
        f"Services: {', '.join(services) if services else 'none'}\n"
        f"Scopes: {len(scopes)}"
    )


async def _action_auth(args: dict) -> str:
    """Run OAuth flow (requires browser on local machine)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_json = _get_credentials_json()
    if not creds_json:
        return (
            "No OAuth credentials configured. Run 'openlama setup' and complete the Google step, "
            "or use 'openlama google auth' from the CLI."
        )

    try:
        flow = InstalledAppFlow.from_client_config(creds_json, ALL_SCOPES)
        creds = await asyncio.to_thread(flow.run_local_server, port=0)
        _save_token(creds)
        from openlama.database import set_setting
        set_setting("google_enabled", "true")
        return "Google authentication successful. All services are now available."
    except Exception as e:
        return f"Authentication failed: {e}"


async def _action_revoke(args: dict) -> str:
    """Revoke Google tokens and disable integration."""
    import httpx
    creds = get_google_creds()
    if creds and creds.token:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": creds.token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except Exception:
            pass

    from openlama.database import set_setting
    set_setting("google_token_enc", "")
    set_setting("google_account_email", "")
    set_setting("google_enabled", "false")
    return "Google integration revoked and disabled."


async def _action_scopes(args: dict) -> str:
    """List available Google service scopes."""
    lines = ["Available Google services and their scopes:\n"]
    for svc, scopes in _SERVICE_SCOPE_MAP.items():
        lines.append(f"  {svc}:")
        for s in scopes:
            lines.append(f"    - {s}")
    return "\n".join(lines)


async def _execute(args: dict) -> str:
    action = args.get("action", "status")
    actions = {
        "status": _action_status,
        "auth": _action_auth,
        "revoke": _action_revoke,
        "scopes": _action_scopes,
    }
    fn = actions.get(action)
    if not fn:
        return f"Unknown action: {action}. Available: {', '.join(actions)}"
    return await fn(args)


register_tool(
    name="google_auth",
    description=(
        "Manage Google account authentication. "
        "Actions: status (check auth state), auth (run OAuth login), "
        "revoke (disconnect Google account), scopes (list available services)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "auth", "revoke", "scopes"],
                "description": "Action to perform",
            },
        },
        "required": ["action"],
    },
    execute=_execute,
)
