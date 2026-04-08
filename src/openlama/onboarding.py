"""Interactive setup wizard — openlama setup."""
import sys
import shutil
import subprocess
import time
import json

from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress

from openlama.config import DATA_DIR, _DEFAULTS

console = Console()


def run_setup():
    """Run the interactive setup wizard."""
    console.print(Panel(
        "  Quick setup. Press Ctrl+C to cancel.",
        title="🤖 openlama — Personal AI Agent",
        border_style="blue",
    ))

    try:
        _step_ollama()
        _step_models()
        _step_channel()
        _step_password()
        _step_features()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]Setup cancelled.[/yellow]")
        sys.exit(1)

    # Create all required directories
    _ensure_directories()

    console.print(Panel(
        "  [green]✅ Setup complete![/green]\n\n"
        "  Start:   [cyan]openlama start[/cyan]\n"
        "  Chat:    [cyan]openlama chat[/cyan]\n"
        "  Doctor:  [cyan]openlama doctor[/cyan]\n"
        "  Config:  [cyan]openlama config list[/cyan]",
        border_style="green",
    ))


def _ensure_directories():
    """Create all required directories after setup."""
    from openlama.config import get_config
    dirs = [
        DATA_DIR,
        DATA_DIR / "skills",
        DATA_DIR / "workflows",
        DATA_DIR / "tmp_uploads",
        Path(get_config("prompts_dir")),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def _save(key: str, value: str):
    from openlama.database import init_db, set_setting
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    set_setting(key, value)


def _step_ollama():
    """Step 1: Check/install Ollama."""
    console.print("\n  [bold]● Step 1/5 — Ollama[/bold]\n")

    if shutil.which("ollama"):
        console.print("  ✓ Ollama is installed")
        # Check if server is running
        try:
            r = httpx.get("http://127.0.0.1:11434/api/version", timeout=3)
            if r.status_code == 200:
                ver = r.json().get("version", "?")
                console.print(f"  ✓ Ollama server running (v{ver})")
                return
        except Exception:
            pass
        console.print("  ⚠ Ollama installed but server not running")
        console.print("  Starting Ollama server...")
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(15):
            time.sleep(1)
            try:
                r = httpx.get("http://127.0.0.1:11434/api/version", timeout=2)
                if r.status_code == 200:
                    console.print("  ✓ Ollama server started")
                    return
            except Exception:
                continue
        console.print("  [red]✗ Could not start Ollama server[/red]")
        return

    # Not installed
    console.print("  ✗ Ollama is not installed")
    import questionary
    install = questionary.confirm("  Install Ollama now?", default=True).ask()
    if not install:
        console.print("  [yellow]Skipped. Install Ollama manually: https://ollama.com[/yellow]")
        return

    console.print("  Installing Ollama...")
    if sys.platform == "win32":
        console.print("  Ollama must be installed manually on Windows.")
        console.print("  Download: https://ollama.com/download/windows")
        return
    elif sys.platform == "darwin" and shutil.which("brew"):
        subprocess.run(["brew", "install", "ollama"], check=True)
    else:
        subprocess.run(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], check=True)

    console.print("  ✓ Ollama installed")
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    console.print("  ✓ Ollama server started")


def _pull_model_with_progress(model: str):
    """Pull a model using Ollama API with Rich progress bar."""
    from rich.progress import Progress, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn

    try:
        with Progress(
            "  {task.description}",
            BarColumn(bar_width=30),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task(model, total=None)

            with httpx.stream(
                "POST",
                "http://127.0.0.1:11434/api/pull",
                json={"name": model, "stream": True},
                timeout=None,
            ) as response:
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    status = data.get("status", "")
                    total = data.get("total", 0)
                    completed = data.get("completed", 0)

                    if total and total > 0:
                        progress.update(task_id, total=total, completed=completed, description=f"{model} ({status})")
                    else:
                        progress.update(task_id, description=f"{model} ({status})")

        console.print(f"  [green]✓ {model} downloaded[/green]")

    except Exception as e:
        console.print(f"  [red]✗ Failed to download {model}: {e}[/red]")


def _step_models():
    """Step 2: Select and download models."""
    console.print("\n  [bold]● Step 2/5 — Models[/bold]\n")

    RECOMMENDED = [
        ("gemma3:4b",        "3.3 GB", "recommended"),
        ("gemma4:e4b",       "9.6 GB", "recommended"),
        ("qwen3.5:4b",       "3.4 GB", "recommended"),
        ("llama3.1:8b",      "4.9 GB", "light"),
        ("qwen3:8b",         "5.2 GB", "light"),
        ("phi4-mini",        "2.5 GB", "light"),
        ("deepseek-r1:8b",   "5.2 GB", "coding"),
        ("qwen2.5-coder:7b", "4.7 GB", "coding"),
        ("gemma3:1b",        "0.8 GB", "ultralight"),
        ("llama3.2:1b",      "1.3 GB", "ultralight"),
    ]

    # Check already installed
    installed = set()
    try:
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=5)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                installed.add(m.get("name", ""))
    except Exception:
        pass

    import questionary
    choices = []
    for tag, size, cat in RECOMMENDED:
        prefix = "✓ " if tag in installed else "  "
        choices.append(questionary.Choice(f"{prefix}{tag:20s} {size:>8s}  [{cat}]", value=tag, checked=tag in installed))
    choices.append(questionary.Choice("  [Custom input]", value="_custom"))

    selected = questionary.checkbox("  Select models to download:", choices=choices).ask()
    if not selected:
        console.print("  [yellow]No models selected[/yellow]")
        return

    # Handle custom
    if "_custom" in selected:
        selected.remove("_custom")
        custom = questionary.text("  Enter model name (e.g., gemma4:26b):").ask()
        if custom:
            selected.append(custom.strip())

    # Download
    to_download = [m for m in selected if m not in installed]
    if to_download:
        console.print(f"\n  Downloading {len(to_download)} model(s)...\n")
        for model in to_download:
            _pull_model_with_progress(model)
    else:
        console.print("  All selected models already installed")

    # Select default
    all_models = list(installed | set(selected))
    if all_models:
        default = questionary.select("  Select default model:", choices=sorted(all_models)).ask()
        if default:
            _save("default_model", default)
            console.print(f"  ✓ Default model: {default}")


def _step_channel():
    """Step 3: Channel + bot token."""
    console.print("\n  [bold]● Step 3/5 — Channel[/bold]\n")

    import questionary
    channel = questionary.select("  Select chat channel:", choices=["Telegram", "CLI only"]).ask()

    if channel == "Telegram":
        token = questionary.text("  Enter Telegram bot token (@BotFather):").ask()
        if token:
            # Verify token
            try:
                r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
                if r.status_code == 200:
                    bot_name = r.json().get("result", {}).get("username", "?")
                    console.print(f"  ✓ Connected: @{bot_name}")
                    _save("telegram_bot_token", token)
                else:
                    console.print(f"  [red]✗ Invalid token (HTTP {r.status_code})[/red]")
            except Exception as e:
                console.print(f"  [red]✗ Connection failed: {e}[/red]")
                _save("telegram_bot_token", token)  # Save anyway
    else:
        console.print("  ✓ CLI-only mode selected")


def _step_password():
    """Step 4: Admin password."""
    console.print("\n  [bold]● Step 4/5 — Password[/bold]\n")

    import questionary
    while True:
        pw = questionary.password("  Set admin password:").ask()
        if not pw or len(pw) < 4:
            console.print("  [red]Password must be at least 4 characters[/red]")
            continue
        pw2 = questionary.password("  Confirm password:").ask()
        if pw != pw2:
            console.print("  [red]Passwords don't match[/red]")
            continue
        break

    from openlama.auth import hash_password
    _save("admin_password_hash", hash_password(pw))
    console.print("  ✓ Password saved")


def _detect_comfyui() -> dict | None:
    """Auto-detect ComfyUI installation across macOS, Linux, Windows."""
    from pathlib import Path
    import platform

    os_name = platform.system()  # "Darwin", "Linux", "Windows"
    home = Path.home()

    def _find_venv_python(base: Path) -> str:
        """Find venv python in a ComfyUI directory."""
        if os_name == "Windows":
            for p in [base / ".venv" / "Scripts" / "python.exe",
                      base / "venv" / "Scripts" / "python.exe"]:
                if p.exists():
                    return str(p)
            return "python"
        else:
            for p in [base / ".venv" / "bin" / "python",
                      base / "venv" / "bin" / "python"]:
                if p.exists():
                    return str(p)
            return "python3"

    def _build_result(label: str, comfy_dir: Path, main_py: str, extra_args: str = "") -> dict:
        py = _find_venv_python(comfy_dir)
        if os_name == "Windows":
            cmd = f'cd /d "{comfy_dir}" && "{py}" "{main_py}" --listen 0.0.0.0 --port 8184 {extra_args}'.strip()
        else:
            cmd = f'cd "{comfy_dir}" && "{py}" "{main_py}" --listen 0.0.0.0 --port 8184 {extra_args}'.strip()
        return {
            "type": label,
            "start_cmd": cmd,
            "output_dir": str(comfy_dir / "output"),
        }

    # ── macOS Desktop App ──
    if os_name == "Darwin":
        app_main = Path("/Applications/ComfyUI.app/Contents/Resources/ComfyUI/main.py")
        docs_dir = home / "Documents" / "ComfyUI"
        if app_main.exists() and docs_dir.exists():
            frontend = "/Applications/ComfyUI.app/Contents/Resources/ComfyUI/web_custom_versions/desktop_app"
            extra = (
                f"--front-end-root {frontend} "
                f"--user-directory {docs_dir}/user "
                f"--input-directory {docs_dir}/input "
                f"--output-directory {docs_dir}/output "
                f"--base-directory {docs_dir} "
                f"--enable-manager"
            )
            return _build_result("macOS Desktop App", docs_dir, str(app_main), extra)

    # ── Windows Desktop App ──
    if os_name == "Windows":
        for app_dir in [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ComfyUI",
            Path(os.environ.get("PROGRAMFILES", "")) / "ComfyUI",
            home / "AppData" / "Local" / "Programs" / "ComfyUI",
        ]:
            main_py = app_dir / "resources" / "ComfyUI" / "main.py"
            if main_py.exists():
                return _build_result("Windows Desktop App", app_dir, str(main_py))

    # ── Common paths (all platforms) ──
    search_dirs = [
        (home / "Documents" / "ComfyUI", "~/Documents/ComfyUI"),
        (home / "ComfyUI", "~/ComfyUI"),
        (home / "comfyui", "~/comfyui"),
    ]

    # Linux: also check common locations
    if os_name == "Linux":
        search_dirs += [
            (Path("/opt/ComfyUI"), "/opt/ComfyUI"),
            (home / ".local" / "share" / "ComfyUI", "~/.local/share/ComfyUI"),
        ]

    # Windows: also check common locations
    if os_name == "Windows":
        search_dirs += [
            (Path("C:/ComfyUI"), "C:/ComfyUI"),
            (Path("D:/ComfyUI"), "D:/ComfyUI"),
        ]

    for comfy_dir, label in search_dirs:
        main_py = comfy_dir / "main.py"
        if main_py.exists():
            return _build_result(f"Local install ({label})", comfy_dir, str(main_py))

    # ── pip/uv installed ──
    comfyui_bin = shutil.which("comfyui")
    if comfyui_bin:
        return {
            "type": "pip/uv install",
            "start_cmd": f"{comfyui_bin} --listen 0.0.0.0 --port 8184",
            "output_dir": "",
        }

    return None


def _step_features():
    """Step 5: Optional features."""
    console.print("\n  [bold]● Step 5/5 — Features[/bold]\n")

    import questionary

    # Auto-detect ComfyUI
    detected = _detect_comfyui()
    if detected:
        console.print(f"  ✓ ComfyUI detected: {detected['type']}")
        comfy = questionary.confirm("  Enable ComfyUI integration?", default=True).ask()
    else:
        console.print("  ℹ ComfyUI not detected")
        comfy = questionary.confirm("  ComfyUI integration (image generation)", default=False).ask()

    _save("comfy_enabled", "true" if comfy else "false")

    if comfy and detected:
        _save("comfy_start_cmd", detected["start_cmd"])
        if detected["output_dir"]:
            _save("comfy_output_dir", detected["output_dir"])
        console.print(f"  ✓ Start command auto-configured")
        console.print(f"  ✓ Auto start/stop enabled (stops 30s after task)")
    elif comfy:
        cmd = questionary.text("  ComfyUI start command:").ask()
        if cmd:
            _save("comfy_start_cmd", cmd)
        output = questionary.text("  ComfyUI output directory:").ask()
        if output:
            _save("comfy_output_dir", output)

    sandbox = questionary.text(
        "  Sandbox path:",
        default=str(_DEFAULTS["tool_sandbox_path"]),
    ).ask()
    if sandbox:
        _save("tool_sandbox_path", sandbox)
