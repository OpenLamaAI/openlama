"""OpenLama brand logo for terminal display."""

from openlama import __version__

# Coral color matching the official logo
_C = "bold rgb(230,120,100)"

LOGO_LARGE = (
    f"[{_C}]"
    "  ██████╗ ██████╗ ███████╗███╗  ██╗██╗      █████╗ ███╗   ███╗ █████╗\n"
    " ██╔═══██╗██╔══██╗██╔════╝████╗ ██║██║     ██╔══██╗████╗ ████║██╔══██╗\n"
    " ██║   ██║██████╔╝█████╗  ██╔██╗██║██║     ███████║██╔████╔██║███████║\n"
    " ██║   ██║██╔═══╝ ██╔══╝  ██║╚████║██║     ██╔══██║██║╚██╔╝██║██╔══██║\n"
    " ╚██████╔╝██║     ███████╗██║ ╚███║███████╗██║  ██║██║ ╚═╝ ██║██║  ██║\n"
    "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚══╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝"
    "[/]"
)

LOGO_COMPACT = (
    f"[{_C}]"
    "╔═╗╔═╗╔═╗╔╗╔╦  ╔═╗╔╦╗╔═╗\n"
    "║ ║╠═╝║╣ ║║║║  ╠═╣║║║╠═╣\n"
    "╚═╝╩  ╚═╝╝╚╝╩═╝╩ ╩╩ ╩╩ ╩"
    "[/]"
)


def print_logo(console=None, compact: bool = False):
    """Print the OpenLama logo to terminal."""
    if console is None:
        from rich.console import Console
        console = Console()

    logo = LOGO_COMPACT if compact else LOGO_LARGE
    width = 30 if compact else 70

    console.print()
    console.print(logo)
    console.print(f"  [dim]{'─' * width}[/]")
    console.print(f"  [dim]Your Local AI Agent[/]"
                  f"{' ' * max(1, width - 38)}"
                  f"[dim rgb(180,180,180)]v{__version__}[/]")
    console.print()
