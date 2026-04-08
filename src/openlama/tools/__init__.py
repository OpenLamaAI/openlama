"""Tool registration — import all tools to trigger registration."""
import sys

from openlama.tools.registry import get_all_tools, get_tool, execute_tool, format_tools_for_ollama
from openlama.config import get_config

_IS_WINDOWS = sys.platform == "win32"


def init_tools():
    """Import all tool modules to register them."""
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
    # Unix-only tools — tmux and process_manager require POSIX shell
    if not _IS_WINDOWS:
        import openlama.tools.process_manager
        import openlama.tools.tmux_tool
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
