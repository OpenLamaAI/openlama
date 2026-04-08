"""Tool registration — import all tools to trigger registration."""
from openlama.tools.registry import get_all_tools, get_tool, execute_tool, format_tools_for_ollama
from openlama.config import get_config

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
    import openlama.tools.process_manager
    import openlama.tools.memory_tool
    import openlama.tools.skill_creator
    import openlama.tools.mcp_manager
    import openlama.tools.cron_tool
    # Conditional tools
    if get_config("obsidian_vault"):
        import openlama.tools.obsidian_tool
