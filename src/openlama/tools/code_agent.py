"""Tool: code_agent — Run Claude Code CLI agent for complex coding tasks.

Requires: tmux + claude CLI installed on Unix.
Supports single execution, parallel multi-task with worktrees, and background runs.
Sessions persist via --continue by default.
"""

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from openlama.config import DATA_DIR
from openlama.tools.registry import register_tool

SESSION_NAME = "openlama-code-agent"
DEFAULT_MAX_TURNS = 20
RUN_TIMEOUT = 600          # 10 min for synchronous run
PARALLEL_TIMEOUT = 600     # 10 min per parallel task
MAX_RESULT_CHARS = 4000
MAX_PARALLEL_RESULT_CHARS = 2000
MAX_PARALLEL_TASKS = 10


# ── Helpers ──────────────────────────────────────────────────


def _find_claude_cli() -> str | None:
    """Find claude CLI binary, checking common paths."""
    found = shutil.which("claude")
    if found:
        return found
    for p in ["/usr/local/bin/claude", "/opt/homebrew/bin/claude",
              str(Path.home() / ".claude" / "bin" / "claude"),
              str(Path.home() / ".local" / "bin" / "claude")]:
        if Path(p).is_file():
            return p
    return None


def _check_deps() -> str | None:
    """Return error message if dependencies are missing."""
    if not shutil.which("tmux"):
        return (
            "tmux is not installed. Required for background execution.\n"
            "Install: brew install tmux (macOS) / apt install tmux (Linux)"
        )
    if not _find_claude_cli():
        return (
            "Claude Code CLI is not installed.\n"
            "Install: npm install -g @anthropic-ai/claude-code"
        )
    return None


def _q(s: str) -> str:
    """Shell-quote a string for safe argument passing."""
    return "'" + s.replace("'", "'\\''") + "'"


def _get_working_dir(cwd_override: str | None) -> str:
    """Determine working directory."""
    if cwd_override:
        p = Path(cwd_override)
        if p.is_dir():
            return str(p.resolve())
    return str(DATA_DIR)


def _is_git_repo(path: str) -> bool:
    """Check if path is inside a git repository."""
    p = Path(path).resolve()
    while p != p.parent:
        if (p / ".git").exists():
            return True
        p = p.parent
    return False


def _has_claude_session(working_dir: str) -> bool:
    """Check if a Claude Code session exists for this working directory."""
    import re
    encoded = re.sub(r'[^a-zA-Z0-9]', '-', working_dir)
    session_dir = Path.home() / ".claude" / "projects" / encoded
    if not session_dir.exists():
        return False
    return any(session_dir.glob("*.jsonl"))


def _truncate(text: str, max_chars: int = MAX_RESULT_CHARS) -> str:
    """Truncate long text, preserving beginning and end."""
    if not text or len(text) <= max_chars:
        return text
    head = max_chars // 3
    tail = max_chars - head - 30
    return text[:head] + "\n\n... (truncated) ...\n\n" + text[-tail:]


async def _run_shell(cmd: str, timeout: int = 30) -> str:
    """Run a shell command and return output."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Timeout ({timeout}s)"

        out = stdout.decode("utf-8", errors="replace")[:8000]
        err = stderr.decode("utf-8", errors="replace")[:2000]

        if proc.returncode != 0:
            return err.strip() or out.strip() or f"exit code {proc.returncode}"
        return out.strip() or "(no output)"
    except Exception as e:
        return f"Error: {e}"


# ── Action: run (synchronous, subprocess) ────────────────────


async def _execute_run(prompt: str, cwd: str, new_session: bool,
                       max_turns: int) -> str:
    """Execute a single Claude Code CLI task and wait for result."""
    claude_bin = _find_claude_cli()
    cmd = [claude_bin, "-p", "--dangerously-skip-permissions",
           "--output-format", "json", "--max-turns", str(max_turns)]

    if not new_session and _has_claude_session(cwd):
        cmd.append("--continue")

    cmd.append(prompt)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=RUN_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return (
                f"[Claude Code] Timed out after {RUN_TIMEOUT}s.\n"
                "Use run_background for long-running tasks."
            )

        raw = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace").strip()

        # Parse JSON output
        try:
            output = json.loads(raw)
            result_text = _truncate(output.get("result", "") or "", MAX_RESULT_CHARS)
            num_turns = output.get("num_turns", "N/A")
            cost = output.get("total_cost_usd", 0)
            session_id = output.get("session_id", "N/A")
            subtype = output.get("subtype", "unknown")

            return (
                f"[Claude Code completed — {subtype}]\n"
                f"Session: {session_id}\n"
                f"Turns: {num_turns} | Cost: ${cost:.4f}\n"
                f"---\n{result_text}"
            )
        except json.JSONDecodeError:
            # Fallback: raw output
            fallback = raw or err or "(no output)"
            return f"[Claude Code completed]\n---\n{_truncate(fallback, MAX_RESULT_CHARS)}"

    except Exception as e:
        return f"[Claude Code] Execution error: {e}"


# ── Action: parallel (multiple subprocesses with worktree isolation) ──


async def _execute_parallel(tasks: list[dict], cwd: str,
                            max_turns: int) -> str:
    """Execute multiple Claude Code tasks in parallel."""
    claude_bin = _find_claude_cli()
    use_worktree = _is_git_repo(cwd)

    async def _run_one(task: dict) -> dict:
        name = task.get("name", f"task-{uuid.uuid4().hex[:6]}")
        task_prompt = task.get("prompt", "")
        if not task_prompt:
            return {"name": name, "result": "No prompt provided.",
                    "success": False, "turns": 0, "cost": 0}

        cmd = [claude_bin, "-p", "--dangerously-skip-permissions",
               "--output-format", "json", "--max-turns", str(max_turns),
               "--session-id", str(uuid.uuid4())]

        if use_worktree:
            cmd.extend(["-w", name])

        cmd.append(task_prompt)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=PARALLEL_TIMEOUT
            )
            raw = stdout.decode("utf-8", errors="replace")
            try:
                output = json.loads(raw)
                return {
                    "name": name,
                    "result": _truncate(output.get("result", "") or "",
                                        MAX_PARALLEL_RESULT_CHARS),
                    "success": output.get("subtype") == "success",
                    "turns": output.get("num_turns", 0),
                    "cost": output.get("total_cost_usd", 0),
                }
            except json.JSONDecodeError:
                return {"name": name,
                        "result": _truncate(raw, MAX_PARALLEL_RESULT_CHARS),
                        "success": proc.returncode == 0,
                        "turns": 0, "cost": 0}
        except asyncio.TimeoutError:
            return {"name": name,
                    "result": f"Timed out ({PARALLEL_TIMEOUT}s)",
                    "success": False, "turns": 0, "cost": 0}
        except Exception as e:
            return {"name": name, "result": f"Error: {e}",
                    "success": False, "turns": 0, "cost": 0}

    results = await asyncio.gather(
        *[_run_one(t) for t in tasks],
        return_exceptions=True,
    )

    # Format collected results
    lines = [f"[Claude Code parallel completed — {len(tasks)} tasks]"]
    total_cost = 0.0

    for r in results:
        if isinstance(r, BaseException):
            lines.append(f"\n## (error)\n{r}")
            continue
        status = "OK" if r["success"] else "FAILED"
        lines.append(
            f"\n## {r['name']} [{status}] "
            f"(turns: {r['turns']}, cost: ${r['cost']:.4f})"
        )
        lines.append(r["result"])
        total_cost += r.get("cost", 0)

    lines.append(f"\n---\nTotal cost: ${total_cost:.4f}")
    return "\n".join(lines)


# ── Action: run_background (tmux session) ────────────────────


async def _execute_run_background(prompt: str, cwd: str,
                                  new_session: bool, max_turns: int) -> str:
    """Start Claude Code in a tmux session for long-running tasks."""
    claude_bin = _find_claude_cli()

    # Check if already running
    check = await _run_shell(
        f"tmux list-panes -t {_q(SESSION_NAME)} "
        f"-F '#{{pane_current_command}}' 2>/dev/null"
    )
    if "claude" in check.lower():
        return (
            "[Claude Code] Already running in background session.\n"
            "Use read_output to check progress, or stop/kill to terminate."
        )

    # Create tmux session if needed
    await _run_shell(
        f"tmux has-session -t {_q(SESSION_NAME)} 2>/dev/null || "
        f"tmux new-session -d -s {_q(SESSION_NAME)}"
    )

    # Build command parts
    cmd_parts = [claude_bin, "-p", "--dangerously-skip-permissions",
                 "--max-turns", str(max_turns)]

    if not new_session and _has_claude_session(cwd):
        cmd_parts.append("--continue")

    # Write a temp script to avoid nested quoting issues with tmux send-keys
    script_fd, script_path = tempfile.mkstemp(suffix=".sh", prefix="code_agent_")
    try:
        with os.fdopen(script_fd, "w") as f:
            f.write("#!/bin/bash\n")
            f.write(f"cd {_q(cwd)}\n")
            cmd_line = " ".join(_q(p) for p in cmd_parts) + " " + _q(prompt)
            f.write(f"{cmd_line}\n")
            f.write(f"rm -f {_q(script_path)}\n")  # self-cleanup
        os.chmod(script_path, 0o755)
    except Exception:
        os.unlink(script_path)
        raise

    await _run_shell(
        f"tmux send-keys -t {_q(SESSION_NAME)} {_q(f'bash {script_path}')} Enter"
    )

    return (
        f"[Claude Code] Background task started.\n"
        f"Session: {SESSION_NAME}\n"
        f"Working directory: {cwd}\n"
        f"Max turns: {max_turns}\n"
        f"Use status/read_output to monitor progress."
    )


# ── Main dispatcher ──────────────────────────────────────────


async def _execute(args: dict) -> str:
    action = args.get("action", "").strip()
    if not action:
        return (
            "Specify an action: run, parallel, run_background, "
            "status, read_output, stop, kill"
        )

    # Dependency check
    err = _check_deps()
    if err:
        return err

    # ── Confirmation gate for execution actions ──
    if action in ("run", "parallel", "run_background"):
        if not args.get("confirmed", False):
            return (
                "Confirmation required before execution.\n"
                "Present the following plan to the user and get approval:\n"
                "1. Task description\n"
                "2. Execution mode (run / parallel / run_background)\n"
                "3. Working directory\n"
                "4. Session mode (new or continue existing)\n"
                "5. Estimated scope and max_turns\n\n"
                "Once the user approves, call again with confirmed=true."
            )

    cwd = _get_working_dir(args.get("cwd"))
    max_turns = args.get("max_turns") or DEFAULT_MAX_TURNS
    new_session = args.get("new_session", False)

    # ── Run (single, synchronous) ──
    if action == "run":
        prompt = (args.get("prompt") or "").strip()
        if not prompt:
            return "prompt is required for run action."
        return await _execute_run(prompt, cwd, new_session, max_turns)

    # ── Parallel ──
    if action == "parallel":
        tasks = args.get("tasks")
        if not tasks or not isinstance(tasks, list) or len(tasks) == 0:
            return (
                "tasks array is required for parallel action.\n"
                "Each item needs 'name' and 'prompt' fields."
            )
        if len(tasks) > MAX_PARALLEL_TASKS:
            return f"Maximum {MAX_PARALLEL_TASKS} parallel tasks allowed."
        return await _execute_parallel(tasks, cwd, max_turns)

    # ── Run Background ──
    if action == "run_background":
        prompt = (args.get("prompt") or "").strip()
        if not prompt:
            return "prompt is required for run_background action."
        return await _execute_run_background(prompt, cwd, new_session, max_turns)

    # ── Status (no confirmation needed) ──
    if action == "status":
        check = await _run_shell(
            f"tmux list-panes -t {_q(SESSION_NAME)} "
            f"-F '#{{pane_current_command}}' 2>/dev/null"
        )
        if not check or "no server" in check.lower() or "error" in check.lower():
            return "[Claude Code] No active background session."

        is_running = "claude" in check.lower()
        return (
            f"[Claude Code] Session '{SESSION_NAME}': "
            f"{'RUNNING' if is_running else 'IDLE'}\n"
            f"Process: {check.strip()}"
        )

    # ── Read Output ──
    if action == "read_output":
        output = await _run_shell(
            f"tmux capture-pane -t {_q(SESSION_NAME)} -p -S -200 2>/dev/null"
        )
        if not output or "no server" in output.lower() or "error" in output.lower():
            return "[Claude Code] No active background session to read."
        return (
            f"[Claude Code output — last 200 lines]\n"
            f"{_truncate(output, MAX_RESULT_CHARS)}"
        )

    # ── Stop (Ctrl+C) ──
    if action == "stop":
        await _run_shell(
            f"tmux send-keys -t {_q(SESSION_NAME)} C-c 2>/dev/null"
        )
        return f"[Claude Code] Interrupt signal sent to session '{SESSION_NAME}'."

    # ── Kill ──
    if action == "kill":
        await _run_shell(
            f"tmux kill-session -t {_q(SESSION_NAME)} 2>/dev/null"
        )
        return f"[Claude Code] Session '{SESSION_NAME}' terminated."

    return (
        f"Unknown action: {action}. "
        "Available: run, parallel, run_background, status, read_output, stop, kill"
    )


# ── Tool registration ───────────────────────────────────────

register_tool(
    name="code_agent",
    description=(
        "Run Claude Code CLI agent for complex coding tasks. "
        "Supports single execution (run), parallel multi-task with worktree isolation (parallel), "
        "and background long-running tasks (run_background). "
        "Sessions persist — subsequent calls continue the same conversation by default. "
        "IMPORTANT: Before calling run/parallel/run_background, ALWAYS present the execution plan "
        "to the user and wait for explicit approval. Only set confirmed=true after user approves."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["run", "parallel", "run_background",
                         "status", "read_output", "stop", "kill"],
                "description": (
                    "run: execute prompt synchronously, wait for result. "
                    "parallel: run multiple sub-tasks concurrently with worktree isolation. "
                    "run_background: start long task in tmux session. "
                    "status: check background task state. "
                    "read_output: capture background terminal output. "
                    "stop: interrupt current execution (Ctrl+C). "
                    "kill: terminate background session."
                ),
            },
            "prompt": {
                "type": "string",
                "description": "Task prompt for Claude Code (required for run/run_background).",
            },
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string",
                                 "description": "Sub-task identifier (used as worktree name)"},
                        "prompt": {"type": "string",
                                   "description": "Sub-task prompt"},
                    },
                    "required": ["name", "prompt"],
                },
                "description": (
                    "Sub-tasks array for parallel action. Max 10 tasks. "
                    "Each runs in an isolated worktree (if git repo) with its own session."
                ),
            },
            "new_session": {
                "type": "boolean",
                "description": (
                    "Start a fresh session without --continue. Default: false. "
                    "Set true only when user explicitly asks for a new/fresh session."
                ),
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for Claude Code (default: openlama data dir).",
            },
            "max_turns": {
                "type": "integer",
                "description": "Max agentic turns per task (default: 20).",
            },
            "confirmed": {
                "type": "boolean",
                "description": (
                    "Must be true to execute run/parallel/run_background. "
                    "Before setting true, ALWAYS present the execution plan to the user "
                    "and wait for their explicit approval."
                ),
            },
        },
        "required": ["action"],
    },
    execute=_execute,
    admin_only=True,
)
