"""Tool: url_fetch – fetch and extract text from a URL."""

import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

from openlama.tools.registry import register_tool


# ── SSRF protection ──────────────────────────────────────

def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private, loopback, or link-local."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return True  # If we can't parse it, block it


def _validate_url_host(url: str) -> str | None:
    """Validate URL host is not a private/internal address.

    Returns error message if blocked, None if safe.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return "Invalid URL: no hostname."

        # Resolve DNS to check actual IP (prevents DNS rebinding)
        try:
            addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            return f"Cannot resolve hostname: {hostname}"

        for info in addr_infos:
            ip_str = info[4][0]
            if _is_private_ip(ip_str):
                return f"Blocked: {hostname} resolves to private/internal address ({ip_str})."

        return None  # Safe
    except Exception as e:
        return f"URL validation error: {e}"


def _extract_text(html: str, max_chars: int = 10000) -> str:
    """Simple HTML to text extraction."""
    # Remove script/style
    text = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", "", html, flags=re.IGNORECASE)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode entities
    import html as html_mod
    text = html_mod.unescape(text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "... (truncated)"
    return text


async def _execute(args: dict) -> str:
    url = args.get("url", "").strip()
    if not url:
        return "Please provide a URL."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # SSRF check: block private/internal addresses
    block_reason = _validate_url_host(url)
    if block_reason:
        return block_reason

    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            event_hooks={"response": [_check_redirect_target]},
        ) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()

        content_type = r.headers.get("content-type", "")
        if "json" in content_type:
            return r.text[:10000]
        elif "text" in content_type or "html" in content_type:
            return _extract_text(r.text)
        else:
            return f"Binary content ({content_type}), size: {len(r.content)} bytes"
    except _SSRFBlocked as e:
        return str(e)
    except Exception as e:
        return f"URL access error: {e}"


class _SSRFBlocked(Exception):
    """Raised when a redirect targets a private/internal address."""
    pass


async def _check_redirect_target(response: httpx.Response) -> None:
    """Event hook: validate each redirect hop against SSRF."""
    if response.is_redirect:
        location = response.headers.get("location", "")
        if location:
            # Resolve relative URLs
            redirect_url = str(response.url.join(location))
            err = _validate_url_host(redirect_url)
            if err:
                raise _SSRFBlocked(f"Redirect blocked (SSRF): {err}")


register_tool(
    name="url_fetch",
    description="Fetch and extract text content from a URL.",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to fetch (e.g., https://example.com)",
            },
        },
        "required": ["url"],
    },
    execute=_execute,
)
