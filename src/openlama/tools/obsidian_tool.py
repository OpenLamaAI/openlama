"""Tool: obsidian – Obsidian vault management via obsidian-cli."""

import asyncio

from openlama.config import get_config_int
from openlama.tools.registry import register_tool


async def _run_obsidian(args: list[str], timeout: int = None) -> str:
    """Run an obsidian-cli command and return output."""
    if timeout is None:
        timeout = get_config_int("code_execution_timeout", 30)
    cmd = ["obsidian-cli"] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Execution timed out ({timeout}s)"

        out = stdout.decode("utf-8", errors="replace")[:8000]
        err = stderr.decode("utf-8", errors="replace")[:2000]

        parts = []
        if out:
            parts.append(out)
        if err and proc.returncode != 0:
            parts.append(f"[Error] {err.strip()}")
            # Provide guidance for common errors
            if "Failed to access vault directory" in err:
                parts.append(
                    "[Hint] The path does not exist. "
                    "Run 'list' on the parent path first to verify exact folder/file names."
                )
            elif "path traversal" in err:
                parts.append("[Hint] Specify the folder name directly instead of '/'.")
        if proc.returncode != 0 and not parts:
            parts.append(f"[exit code: {proc.returncode}]")
        return "\n".join(parts) if parts else "(empty result)"

    except FileNotFoundError:
        return "obsidian-cli is not installed. Install with: brew install obsidian-cli"
    except Exception as e:
        return f"Obsidian CLI execution error: {e}"


async def _execute(args: dict) -> str:
    action = args.get("action", "").strip()
    vault = args.get("vault", "").strip() or None
    note = args.get("note", "").strip() or None
    content = args.get("content", "").strip() or None
    destination = args.get("destination", "").strip() or None
    query = args.get("query", "").strip() or None
    key = args.get("key", "").strip() or None
    value = args.get("value", "").strip() or None

    if not action:
        return (
            "Please specify an action:\n"
            "list, read, create, append, delete, move, search, "
            "search_content, daily, frontmatter_get, frontmatter_set, frontmatter_delete"
        )

    vault_args = ["-v", vault] if vault else []

    # ── List files/folders ──
    if action == "list":
        cmd = ["list"] + vault_args
        if note and note not in ("/", ".", "./", "root"):
            cmd.append(note)
        return await _run_obsidian(cmd)

    # ── Read note ──
    if action == "read":
        if not note:
            return "Please specify the note parameter."
        cmd = ["print"] + vault_args + [note]
        return await _run_obsidian(cmd)

    # ── Create note ──
    if action == "create":
        if not note:
            return "Please specify the note parameter (e.g., 'folder/note_name')."
        cmd = ["create"] + vault_args + [note]
        if content:
            cmd += ["-c", content]
        return await _run_obsidian(cmd)

    # ── Append to note ──
    if action == "append":
        if not note:
            return "Please specify the note parameter."
        if not content:
            return "Please specify the content parameter."
        cmd = ["create", "-a"] + vault_args + [note, "-c", content]
        return await _run_obsidian(cmd)

    # ── Delete note ──
    if action == "delete":
        if not note:
            return "Please specify the note parameter."
        cmd = ["delete"] + vault_args + [note]
        return await _run_obsidian(cmd)

    # ── Move/rename note ──
    if action == "move":
        if not note:
            return "Please specify the note parameter (source note)."
        if not destination:
            return "Please specify the destination parameter (target path/name)."
        cmd = ["move"] + vault_args + [note, destination]
        return await _run_obsidian(cmd)

    # ── Fuzzy search by name ──
    if action == "search":
        if not query:
            return "Please specify the query parameter."
        cmd = ["search"] + vault_args + [query]
        return await _run_obsidian(cmd)

    # ── Search by content ──
    if action == "search_content":
        if not query:
            return "Please specify the query parameter."
        cmd = ["search-content"] + vault_args + [query]
        return await _run_obsidian(cmd)

    # ── Daily note ──
    if action == "daily":
        cmd = ["daily"] + vault_args
        return await _run_obsidian(cmd)

    # ── Frontmatter get ──
    if action == "frontmatter_get":
        if not note:
            return "Please specify the note parameter."
        cmd = ["frontmatter", "--print"] + vault_args + [note]
        return await _run_obsidian(cmd)

    # ── Frontmatter set ──
    if action == "frontmatter_set":
        if not note:
            return "Please specify the note parameter."
        if not key:
            return "Please specify the key parameter."
        if value is None:
            return "Please specify the value parameter."
        cmd = ["frontmatter", "--edit", "-k", key, "--value", value] + vault_args + [note]
        return await _run_obsidian(cmd)

    # ── Frontmatter delete ──
    if action == "frontmatter_delete":
        if not note:
            return "Please specify the note parameter."
        if not key:
            return "Please specify the key parameter."
        cmd = ["frontmatter", "--delete", "-k", key] + vault_args + [note]
        return await _run_obsidian(cmd)

    return f"Unknown action: {action}"


register_tool(
    name="obsidian",
    description=(
        "Obsidian note management tool. List, read, create, edit, delete, move, and search notes in a vault. "
        "Also supports frontmatter (YAML) viewing/editing and daily note creation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "Action to perform: list (file list), read (read note), create (create note), "
                    "append (append to note), delete (delete note), move (move/rename note), "
                    "search (fuzzy search by name), search_content (search by content), daily (daily note), "
                    "frontmatter_get (view frontmatter), frontmatter_set (edit frontmatter), "
                    "frontmatter_delete (delete frontmatter key)"
                ),
            },
            "note": {
                "type": "string",
                "description": "Note name or path (e.g., '000_INBOX/memo', 'MY_NOTE'). Used as folder path for list action",
            },
            "content": {
                "type": "string",
                "description": "Note content (used for create, append). Supports markdown",
            },
            "destination": {
                "type": "string",
                "description": "Destination path (used for move, e.g., '400_ARCHIVE/old_note')",
            },
            "query": {
                "type": "string",
                "description": "Search query (used for search, search_content)",
            },
            "vault": {
                "type": "string",
                "description": "Vault name (uses default vault if not specified)",
            },
            "key": {
                "type": "string",
                "description": "Frontmatter key (used for frontmatter_set, frontmatter_delete)",
            },
            "value": {
                "type": "string",
                "description": "Frontmatter value (used for frontmatter_set)",
            },
        },
        "required": ["action"],
    },
    execute=_execute,
    admin_only=True,
)
