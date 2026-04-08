"""Tool: git – Git repository operations (admin only)."""

import asyncio
import os
import shutil

from openlama.config import get_config_int
from openlama.tools.registry import register_tool


async def _run_git(args: list[str], cwd: str = None, timeout: int = None) -> str:
    """Run a git command and return output."""
    if not shutil.which("git"):
        return "git is not installed. Please install Git: https://git-scm.com"
    if timeout is None:
        timeout = get_config_int("code_execution_timeout", 30)
    cmd = ["git"] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
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
            parts.append(f"[stderr]\n{err}")
        parts.append(f"[exit code: {proc.returncode}]")
        return "\n".join(parts)

    except FileNotFoundError:
        return "Git is not installed."
    except Exception as e:
        return f"Git execution error: {e}"


async def _execute(args: dict) -> str:
    action = args.get("action", "").strip()
    repo_path = args.get("repo_path", "").strip() or None
    extra = args.get("args", "").strip()

    if not action:
        return "Please specify an action (status, log, diff, branch, commit, push, pull, checkout, add, stash)"

    # Map action to git subcommands
    safe_actions = {
        "status": ["status", "--short"],
        "log": ["log", "--oneline", "-20"],
        "diff": ["diff", "--stat"],
        "diff_full": ["diff"],
        "branch": ["branch", "-a"],
        "remote": ["remote", "-v"],
        "stash_list": ["stash", "list"],
        "show": ["show", "--stat", "HEAD"],
        "blame": ["blame"],
    }

    write_actions = {"commit", "push", "pull", "checkout", "add", "stash", "merge", "reset", "tag", "fetch"}

    if action in safe_actions:
        git_args = list(safe_actions[action])
        if extra:
            git_args.extend(extra.split())
        return await _run_git(git_args, cwd=repo_path)

    if action in write_actions:
        git_args = [action]
        if extra:
            git_args.extend(extra.split())
        return await _run_git(git_args, cwd=repo_path)

    # Fallback: pass action + extra directly
    git_args = [action]
    if extra:
        git_args.extend(extra.split())
    return await _run_git(git_args, cwd=repo_path)


register_tool(
    name="git",
    description=(
        "Perform Git repository operations. Execute Git commands such as status, log, diff, branch, commit, push, pull, "
        "checkout, add, stash, merge, fetch, etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "Git command: status, log, diff, diff_full, branch, commit, push, pull, "
                    "checkout, add, stash, stash_list, merge, fetch, remote, show, blame, reset, tag"
                ),
            },
            "repo_path": {
                "type": "string",
                "description": "Git repository path (default: current directory)",
            },
            "args": {
                "type": "string",
                "description": "Additional arguments (e.g., '-m \"commit message\"' for commit, 'branch-name' for checkout)",
            },
        },
        "required": ["action"],
    },
    execute=_execute,
    admin_only=True,
)
