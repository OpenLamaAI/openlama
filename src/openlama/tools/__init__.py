"""Tool registration — import all tools to trigger registration."""
import os
import sys
from pathlib import Path

from openlama.tools.registry import get_all_tools, get_tool, execute_tool, format_tools_for_ollama
from openlama.config import get_config, IS_ANDROID

_IS_WINDOWS = sys.platform == "win32"


def _ensure_daemon_env():
    """Ensure essential environment variables for daemon processes.

    launchd/systemd often start with a minimal PATH and missing env vars
    like USER, which breaks Keychain access for tools like Claude Code CLI.
    """
    # PATH: add common binary locations
    extra = [
        "/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin",
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".claude" / "bin"),
    ]
    current = os.environ.get("PATH", "")
    additions = [p for p in extra if p not in current and Path(p).is_dir()]
    if additions:
        os.environ["PATH"] = ":".join(additions) + ":" + current

    # USER: required for macOS Keychain access (Claude Code auth)
    if not os.environ.get("USER"):
        import getpass
        try:
            os.environ["USER"] = getpass.getuser()
        except Exception:
            pass


def init_tools():
    """Import all tool modules to register them."""
    _ensure_daemon_env()
    import openlama.tools.datetime_tool
    import openlama.tools.calculator
    import openlama.tools.web_search
    import openlama.tools.url_fetch
    import openlama.tools.code_runner
    import openlama.tools.shell_command
    import openlama.tools.file_read
    import openlama.tools.file_write
    import openlama.tools.image_generate
    import openlama.tools.image_edit
    import openlama.tools.git_tool
    import openlama.tools.memory_tool
    import openlama.tools.skill_creator
    import openlama.tools.mcp_manager
    import openlama.tools.cron_tool
    import openlama.tools.update_tool
    import openlama.tools.process_manager
    # tmux is Unix-only (no Windows equivalent)
    if not _IS_WINDOWS:
        import openlama.tools.tmux_tool
    # code_agent: requires tmux + claude CLI (Unix-only)
    if not _IS_WINDOWS:
        import shutil
        if shutil.which("tmux") and shutil.which("claude"):
            import openlama.tools.code_agent
    # Conditional tools — whisper: auto-detect if faster-whisper is installed
    stt_config = get_config("stt_enabled", "auto").lower()
    if stt_config != "false":
        try:
            import faster_whisper  # noqa: F401
            import openlama.tools.whisper_tool
        except ImportError:
            pass
    if get_config("obsidian_vault"):
        import openlama.tools.obsidian_tool
    # Android-only: Termux device control
    if IS_ANDROID:
        import openlama.tools.termux_tool
