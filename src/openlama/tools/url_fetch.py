"""Tool: url_fetch – fetch and extract text from a URL."""

import ipaddress
import re
from urllib.parse import urlparse

import httpx

from openlama.tools.registry import register_tool


def _is_private_url(url: str) -> bool:
    """Block requests to private/internal network addresses (SSRF protection)."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return True
        # Block common internal hostnames
        if hostname in ("localhost", "metadata.google.internal"):
            return True
        # Check if hostname is a literal IP address
        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        except ValueError:
            pass  # Not a literal IP, it's a domain name
        # Resolve domain and check IPs
        import socket
        try:
            for info in socket.getaddrinfo(hostname, None):
                addr = info[4][0]
                try:
                    ip = ipaddress.ip_address(addr)
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                        return True
                except ValueError:
                    continue
        except socket.gaierror:
            # DNS resolution failed — allow the request; httpx will handle the error
            return False
    except Exception:
        return False
    return False


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

    if _is_private_url(url):
        return "Access denied: requests to private/internal network addresses are blocked."

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()

        content_type = r.headers.get("content-type", "")
        if "json" in content_type:
            return r.text[:10000]
        elif "text" in content_type or "html" in content_type:
            return _extract_text(r.text)
        else:
            return f"Binary content ({content_type}), size: {len(r.content)} bytes"
    except Exception as e:
        return f"URL access error: {e}"


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
