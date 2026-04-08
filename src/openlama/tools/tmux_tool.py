"""Tool: tmux — Full tmux session, window, and pane management."""

import asyncio
import shutil

from openlama.config import get_config_int
from openlama.tools.registry import register_tool


async def _run(cmd: str, timeout: int = None) -> str:
    """Run a shell command and return output."""
    if timeout is None:
        timeout = get_config_int("code_execution_timeout", 30)
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


def _check_tmux() -> str | None:
    """Return error message if tmux is not installed."""
    if not shutil.which("tmux"):
        return "tmux is not installed. Install it with: brew install tmux (macOS) or apt install tmux (Linux)"
    return None


async def _execute(args: dict) -> str:
    action = args.get("action", "").strip()
    if not action:
        return (
            "Specify an action: list_sessions, new_session, kill_session, rename_session, "
            "attach, detach, list_windows, new_window, kill_window, rename_window, "
            "select_window, list_panes, split, select_pane, send_keys, capture, resize_pane, "
            "swap_pane, swap_window, move_window, info"
        )

    err = _check_tmux()
    if err:
        return err

    session = args.get("session", "").strip()
    name = args.get("name", "").strip()
    target = args.get("target", "").strip()
    command = args.get("command", "").strip()
    direction = args.get("direction", "horizontal").strip()
    size = args.get("size", "").strip()

    # ── Session management ──

    if action == "list_sessions":
        return await _run("tmux list-sessions -F '#{session_name}: #{session_windows} windows (created #{session_created_string}) #{?session_attached,(attached),}' 2>/dev/null || echo 'No tmux server running'")

    if action == "new_session":
        s = name or session or "main"
        cmd = f"tmux new-session -d -s {_q(s)}"
        if command:
            cmd += f" {_q(command)}"
        result = await _run(cmd)
        if "duplicate" in result.lower():
            return f"Session '{s}' already exists."
        return f"Session '{s}' created." if "exit" not in result.lower() else result

    if action == "kill_session":
        if not session:
            return "session name is required."
        if session == "all":
            return await _run("tmux kill-server 2>/dev/null && echo 'All sessions killed.' || echo 'No tmux server running.'")
        return await _run(f"tmux kill-session -t {_q(session)}")

    if action == "rename_session":
        if not session or not name:
            return "Both session (current name) and name (new name) are required."
        return await _run(f"tmux rename-session -t {_q(session)} {_q(name)}")

    if action == "attach":
        s = session or ""
        if s:
            return await _run(f"tmux attach-session -t {_q(s)} 2>&1 || echo 'Cannot attach from non-interactive shell. Use: tmux attach -t {s}'")
        return "Use in your terminal: tmux attach"

    if action == "detach":
        if not session:
            return "session name is required."
        return await _run(f"tmux detach-client -s {_q(session)} 2>/dev/null || echo 'No client attached to session {session}'")

    # ── Window management ──

    if action == "list_windows":
        s = session or ""
        if s:
            return await _run(f"tmux list-windows -t {_q(s)} -F '#{{window_index}}: #{{window_name}}#{{?window_active, (active),}} (#{{pane_current_command}})' 2>/dev/null || echo 'Session not found'")
        return await _run("tmux list-windows -a -F '#{session_name}:##{window_index}: #{window_name}#{?window_active, (active),}' 2>/dev/null || echo 'No tmux server running'")

    if action == "new_window":
        if not session:
            return "session name is required."
        cmd = f"tmux new-window -t {_q(session)}"
        if name:
            cmd += f" -n {_q(name)}"
        if command:
            cmd += f" {_q(command)}"
        await _run(cmd)
        return f"New window created in session '{session}'." + (f" Name: {name}" if name else "")

    if action == "kill_window":
        if not target:
            return "target is required (e.g., 'session:0' or 'session:window_name')."
        return await _run(f"tmux kill-window -t {_q(target)}")

    if action == "rename_window":
        if not target or not name:
            return "Both target (session:window_index) and name (new name) are required."
        return await _run(f"tmux rename-window -t {_q(target)} {_q(name)}")

    if action == "select_window":
        if not target:
            return "target is required (e.g., 'session:0')."
        return await _run(f"tmux select-window -t {_q(target)}")

    if action == "move_window":
        if not target or not name:
            return "target (source session:window) and name (dest session:index) are required."
        return await _run(f"tmux move-window -s {_q(target)} -t {_q(name)}")

    if action == "swap_window":
        if not target or not name:
            return "target (session:window1) and name (session:window2) are required."
        return await _run(f"tmux swap-window -s {_q(target)} -t {_q(name)}")

    # ── Pane management ──

    if action == "list_panes":
        t = target or session
        if not t:
            return await _run("tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index}: #{pane_current_command} (#{pane_width}x#{pane_height})#{?pane_active, (active),}' 2>/dev/null || echo 'No tmux server running'")
        return await _run(f"tmux list-panes -t {_q(t)} -F '#{{pane_index}}: #{{pane_current_command}} (#{{pane_width}}x#{{pane_height}})#{{?pane_active, (active),}}' 2>/dev/null || echo 'Target not found'")

    if action == "split":
        t = target or session
        if not t:
            return "session or target is required."
        flag = "-v" if direction == "vertical" else "-h"
        cmd = f"tmux split-window {flag} -t {_q(t)}"
        if size:
            cmd += f" -l {_q(size)}"
        if command:
            cmd += f" {_q(command)}"
        await _run(cmd)
        return f"Pane split {direction}ly in {t}."

    if action == "select_pane":
        if not target:
            return "target is required (e.g., 'session:0.1')."
        return await _run(f"tmux select-pane -t {_q(target)}")

    if action == "resize_pane":
        if not target:
            return "target is required."
        if not size:
            return "size is required (e.g., '20' for 20 lines/cols)."
        d_flag = {"up": "-U", "down": "-D", "left": "-L", "right": "-R"}.get(direction, "-D")
        return await _run(f"tmux resize-pane -t {_q(target)} {d_flag} {size}")

    if action == "swap_pane":
        if not target or not name:
            return "target (source pane) and name (dest pane) are required."
        return await _run(f"tmux swap-pane -s {_q(target)} -t {_q(name)}")

    # ── Interaction ──

    if action == "send_keys":
        if not target and not session:
            return "session or target is required."
        if not command:
            return "command (keys to send) is required."
        t = target or session
        return await _run(f"tmux send-keys -t {_q(t)} {_q(command)} Enter")

    if action == "capture":
        t = target or session
        if not t:
            return "session or target is required."
        lines = size or "100"
        return await _run(f"tmux capture-pane -t {_q(t)} -p -S -{lines}")

    # ── Info ──

    if action == "info":
        parts = [
            "tmux list-sessions -F '#{session_name}: #{session_windows} win#{?session_attached, (attached),}' 2>/dev/null || echo 'No server'",
            "echo '---'",
            "tmux display-message -p 'Server PID: #{pid}, Version: #{version}' 2>/dev/null || echo 'tmux not running'",
        ]
        return await _run(" && ".join(parts))

    return f"Unknown action: {action}. Use list_sessions, new_session, kill_session, rename_session, list_windows, new_window, kill_window, split, send_keys, capture, info"


def _q(s: str) -> str:
    """Shell-quote a string for safe tmux argument passing."""
    # Use single quotes, escaping any existing single quotes
    return "'" + s.replace("'", "'\\''") + "'"


register_tool(
    name="tmux",
    description=(
        "Full tmux terminal multiplexer control. "
        "Manage sessions, windows, panes — create, list, split, send commands, capture output, and more."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_sessions", "new_session", "kill_session", "rename_session",
                    "attach", "detach",
                    "list_windows", "new_window", "kill_window", "rename_window",
                    "select_window", "move_window", "swap_window",
                    "list_panes", "split", "select_pane", "resize_pane", "swap_pane",
                    "send_keys", "capture",
                    "info",
                ],
                "description": "Action to perform",
            },
            "session": {
                "type": "string",
                "description": "Session name (for session-level operations)",
            },
            "name": {
                "type": "string",
                "description": "New name (for rename, new_window) or destination target (for swap/move)",
            },
            "target": {
                "type": "string",
                "description": "Target specifier (e.g., 'session:window.pane' like 'main:0.1')",
            },
            "command": {
                "type": "string",
                "description": "Command to run (new_session, new_window, split) or keys to send (send_keys)",
            },
            "direction": {
                "type": "string",
                "enum": ["horizontal", "vertical", "up", "down", "left", "right"],
                "description": "Split direction (horizontal/vertical) or resize direction (up/down/left/right)",
            },
            "size": {
                "type": "string",
                "description": "Size for split/resize (e.g., '20' lines/cols, '50%') or line count for capture",
            },
        },
        "required": ["action"],
    },
    execute=_execute,
    admin_only=True,
)
