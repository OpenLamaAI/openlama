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

from openlama.config import DATA_DIR, TERMUX, IS_ANDROID, _DEFAULTS

console = Console()


def _get_existing(key: str) -> str:
    """Get existing config value from DB (for re-setup)."""
    try:
        from openlama.database import init_db, get_setting
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        init_db()
        return get_setting(key) or ""
    except Exception:
        return ""


def run_setup():
    """Run the interactive setup wizard."""
    console.print(Panel(
        "  Quick setup. Press Ctrl+C to cancel.\n"
        "  [dim]Leave blank to keep existing value.[/dim]",
        title="🤖 openlama — Personal AI Agent",
        border_style="blue",
    ))

    try:
        _step_ollama()
        _step_models()
        _step_channel()
        _step_password()
        _step_features()
        _step_stt()
        _step_obsidian()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]Setup cancelled.[/yellow]")
        sys.exit(1)

    # Create all required directories
    _ensure_directories()

    # Restart daemon if running so new config takes effect
    _restart_daemon_if_running()

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


def _restart_daemon_if_running():
    """Restart daemon if it's currently running, so new config takes effect."""
    try:
        from openlama.daemon import _read_pid, restart_daemon
        pid = _read_pid()
        if pid:
            console.print("\n  [cyan]⟳ Restarting daemon to apply new settings...[/cyan]")
            restart_daemon()
            console.print("  [green]✓ Daemon restarted[/green]")
    except Exception as e:
        console.print(f"  [yellow]⚠ Could not restart daemon: {e}[/yellow]")
        console.print("  [dim]Run manually: openlama restart[/dim]")


def _get_ollama_url() -> str:
    """Get the current ollama_base URL (DB → env → default)."""
    try:
        from openlama.database import get_setting
        val = get_setting("ollama_base")
        if val:
            return val.rstrip("/")
    except Exception:
        pass
    import os as _os
    return _os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434").rstrip("/")


def _save(key: str, value: str):
    from openlama.database import init_db, set_setting
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    set_setting(key, value)


def _step_ollama():
    """Step 1: Check/install Ollama or connect to remote server."""
    console.print("\n  [bold]● Step 1/7 — Ollama[/bold]\n")

    import questionary

    # Ask: local or remote?
    existing_base = _get_existing("ollama_base") or _get_ollama_url()
    is_remote = not any(h in existing_base for h in ("127.0.0.1", "localhost", "0.0.0.0"))

    if TERMUX:
        console.print("  [dim]Mobile environment detected[/dim]\n")

    mode = questionary.select(
        "  Ollama server location:",
        choices=[
            questionary.Choice("Local (this machine)", value="local"),
            questionary.Choice("Remote server (recommended for mobile)", value="remote"),
        ],
        default="remote" if (TERMUX or is_remote) else "local",
    ).ask()

    if mode == "remote":
        url = questionary.text(
            "  Remote Ollama URL:",
            default=existing_base if is_remote else "http://192.168.1.100:11434",
        ).ask()
        if url:
            url = url.rstrip("/")
            _save("ollama_base", url)
            console.print(f"  Checking connection to {url}...")
            try:
                r = httpx.get(f"{url}/api/version", timeout=5)
                if r.status_code == 200:
                    ver = r.json().get("version", "?")
                    console.print(f"  ✓ Remote Ollama connected (v{ver})")
                    return
            except Exception:
                pass
            console.print("  [yellow]⚠ Cannot connect now. Make sure the server is running.[/yellow]")
            console.print(f"  [dim]Saved URL: {url} — you can change later with 'openlama config set ollama_base <url>'[/dim]")
        return

    # Local mode
    _save("ollama_base", "http://127.0.0.1:11434")

    if shutil.which("ollama"):
        console.print("  ✓ Ollama is installed")
        try:
            r = httpx.get(f"{_get_ollama_url()}/api/version", timeout=3)
            if r.status_code == 200:
                ver = r.json().get("version", "?")
                console.print(f"  ✓ Ollama server running (v{ver})")
                return
        except Exception:
            pass
        console.print("  ⚠ Ollama installed but server not running")
        console.print("  Starting Ollama server...")
        from openlama.ollama_client import start_ollama_service
        started, method = start_ollama_service()
        if started:
            for _ in range(15):
                time.sleep(1)
                try:
                    r = httpx.get(f"{_get_ollama_url()}/api/version", timeout=2)
                    if r.status_code == 200:
                        console.print(f"  ✓ Ollama server started ({method})")
                        return
                except Exception:
                    continue
        console.print("  [red]✗ Could not start Ollama server[/red]")
        return

    # Not installed — install
    console.print("  ✗ Ollama is not installed")
    install = questionary.confirm("  Install Ollama now?", default=True).ask()
    if not install:
        console.print("  [yellow]Skipped. Install Ollama manually: https://ollama.com[/yellow]")
        return

    console.print("  Installing Ollama...")
    if TERMUX:
        subprocess.run(["pkg", "install", "-y", "tur-repo"], capture_output=True)
        result = subprocess.run(["pkg", "install", "-y", "ollama"], capture_output=True, text=True)
        if result.returncode == 0:
            console.print("  ✓ Ollama installed via Termux")
        else:
            console.print("  [red]✗ Failed. Try manually: pkg install tur-repo && pkg install ollama[/red]")
            return
    elif sys.platform == "win32":
        console.print("  Ollama must be installed manually on Windows.")
        console.print("  Download: https://ollama.com/download/windows")
        return
    elif sys.platform == "darwin" and shutil.which("brew"):
        subprocess.run(["brew", "install", "ollama"], check=True)
    elif shutil.which("curl"):
        subprocess.run(["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], check=True)
    else:
        console.print("  [red]✗ curl not found. Install Ollama manually: https://ollama.com[/red]")
        return

    console.print("  ✓ Ollama installed")
    from openlama.ollama_client import start_ollama_service
    started, method = start_ollama_service()
    if started:
        time.sleep(3)
        console.print(f"  ✓ Ollama server started ({method})")
    else:
        console.print("  [yellow]⚠ Installed but could not auto-start. Run 'ollama serve' manually.[/yellow]")


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
                f"{_get_ollama_url()}/api/pull",
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
    console.print("\n  [bold]● Step 2/7 — Models[/bold]\n")

    from openlama.config import is_ollama_remote

    if IS_ANDROID:
        console.print("  [dim]Mobile environment — lightweight models recommended[/dim]\n")

    if is_ollama_remote():
        # Remote server: just ask for model name, don't need lightweight
        import questionary
        console.print("  [dim]Using remote server — select a model installed on the server[/dim]\n")
        installed = set()
        try:
            r = httpx.get(f"{_get_ollama_url()}/api/tags", timeout=5)
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    installed.add(m.get("name", ""))
        except Exception:
            pass

        if installed:
            default = questionary.select("  Select default model:", choices=sorted(installed)).ask()
            if default:
                _save("default_model", default)
                console.print(f"  ✓ Default model: {default}")
        else:
            console.print("  [yellow]Cannot reach remote server. Set model later with 'openlama config set default_model <model>'[/yellow]")
        return

    MOBILE_RECOMMENDED = [
        ("gemma4:e2b",       "7.2 GB", "recommended — mobile optimized"),
        ("gemma3:4b",        "3.3 GB", "recommended"),
        ("phi4-mini",        "2.5 GB", "light"),
        ("gemma3:1b",        "0.8 GB", "ultralight"),
        ("llama3.2:1b",      "1.3 GB", "ultralight"),
    ]

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

    model_list = MOBILE_RECOMMENDED if IS_ANDROID else RECOMMENDED

    # Check already installed
    installed = set()
    try:
        r = httpx.get(f"{_get_ollama_url()}/api/tags", timeout=5)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                installed.add(m.get("name", ""))
    except Exception:
        pass

    import questionary
    choices = []
    recommended_tags = {tag for tag, _, _ in model_list}
    for tag, size, cat in model_list:
        prefix = "✓ " if tag in installed else "  "
        choices.append(questionary.Choice(f"{prefix}{tag:20s} {size:>8s}  [{cat}]", value=tag, checked=tag in installed))
    # Add installed models not in recommended list
    for tag in sorted(installed - recommended_tags):
        choices.append(questionary.Choice(f"✓ {tag:20s}            [installed]", value=tag, checked=True))
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
    console.print("\n  [bold]● Step 3/7 — Channel[/bold]\n")

    existing_token = _get_existing("telegram_bot_token")
    if existing_token:
        masked = existing_token[:8] + "..." + existing_token[-4:]
        console.print(f"  [dim]Current token: {masked}[/dim]")

    import questionary
    channel = questionary.select("  Select chat channel:", choices=["Telegram", "CLI only"]).ask()

    if channel == "Telegram":
        hint = " (blank = keep current)" if existing_token else ""
        token = questionary.text(f"  Enter Telegram bot token{hint}:").ask()
        token = (token or "").strip()

        if not token and existing_token:
            console.print("  ✓ Keeping existing token")
            return

        if not token:
            console.print("  [yellow]No token provided[/yellow]")
            return

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
    console.print("\n  [bold]● Step 4/7 — Password[/bold]\n")

    existing_hash = _get_existing("admin_password_hash")
    if existing_hash:
        console.print("  [dim]Password already set. Leave blank to keep current.[/dim]")

    import questionary
    while True:
        pw = questionary.password("  Set admin password:").ask()
        pw = (pw or "").strip()

        # Allow skipping if password already exists
        if not pw and existing_hash:
            console.print("  ✓ Keeping existing password")
            return

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
    console.print("\n  [bold]● Step 5/7 — Features[/bold]\n")

    import questionary

    if IS_ANDROID:
        # Mobile: skip ComfyUI, check Termux:API
        _save("comfy_enabled", "false")
        console.print("  [dim]ComfyUI: disabled on mobile[/dim]")
        if shutil.which("termux-battery-status"):
            console.print("  ✓ Termux:API detected — device control tools enabled")
        else:
            console.print("  ⚠ Termux:API not installed")
            console.print("    Install: F-Droid > Termux:API app, then 'pkg install termux-api'")
        sandbox = str(_DEFAULTS["tool_sandbox_path"])
        _save("tool_sandbox_path", sandbox)
        return

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


def _step_stt():
    """Step 6: Speech-to-text (STT) for voice messages."""
    console.print("\n  [bold]● Step 6/7 — Voice Recognition (STT)[/bold]\n")

    import questionary

    # Check if already installed
    stt_installed = False
    try:
        import faster_whisper
        stt_installed = True
    except ImportError:
        pass

    existing = _get_existing("stt_enabled")

    if stt_installed:
        console.print("  ✓ faster-whisper is installed")
        _save("stt_enabled", "true")
        console.print("  ✓ Voice recognition enabled")
        return

    console.print("  Voice recognition converts audio/voice messages to text.")
    console.print("  [dim]Requires: faster-whisper (~200MB download)[/dim]")
    install = questionary.confirm("  Enable voice recognition (STT)?", default=True).ask()

    if not install:
        _save("stt_enabled", "false")
        console.print("  ✓ Voice recognition disabled (can enable later via config)")
        return

    console.print("\n  Installing faster-whisper...")
    if _pip_install("faster-whisper"):
        _save("stt_enabled", "true")
        console.print("  [green]✓ faster-whisper installed[/green]")
        console.print("  ✓ Voice recognition enabled")
    else:
        _save("stt_enabled", "false")
        console.print("  [dim]You can install manually: pip install faster-whisper[/dim]")


def _find_obsidian_cli() -> str | None:
    """Find obsidian-cli, checking common paths beyond PATH."""
    found = shutil.which("obsidian-cli")
    if found:
        return found
    import os
    extra = ["/opt/homebrew/bin/obsidian-cli", "/usr/local/bin/obsidian-cli"]
    gopath = os.environ.get("GOPATH", str(Path.home() / "go"))
    extra.append(os.path.join(gopath, "bin", "obsidian-cli"))
    for p in extra:
        if os.path.isfile(p):
            return p
    return None


def _step_obsidian():
    """Step 7: Obsidian vault integration."""
    console.print("\n  [bold]● Step 7/7 — Obsidian Notes[/bold]\n")

    import questionary

    cli_path = _find_obsidian_cli()
    existing_vault = _get_existing("obsidian_vault")

    if cli_path:
        console.print(f"  ✓ obsidian-cli is installed ({cli_path})")
    else:
        console.print("  Obsidian integration lets the AI read/create/search your notes.")
        console.print("  [dim]Requires: obsidian-cli (brew install)[/dim]")

    enable = questionary.confirm(
        "  Enable Obsidian integration?",
        default=bool(existing_vault or cli_path),
    ).ask()

    if not enable:
        _save("obsidian_vault", "")
        console.print("  ✓ Obsidian integration disabled")
        return

    # Install obsidian-cli if needed
    if not cli_path:
        console.print("\n  Installing obsidian-cli...")
        if _install_obsidian_cli():
            cli_path = _find_obsidian_cli()
            console.print(f"  [green]✓ obsidian-cli installed[/green]")
        else:
            console.print("  [red]✗ Installation failed[/red]")
            console.print("  [dim]Install manually: brew tap yakitrak/yakitrak && brew install obsidian-cli[/dim]")
            console.print("  [yellow]⚠ Obsidian tool will be enabled but commands will fail until CLI is installed.[/yellow]")

    # Configure vault
    if existing_vault:
        console.print(f"  [dim]Current vault: {existing_vault}[/dim]")

    # Try to detect vaults
    detected_vaults = _detect_obsidian_vaults()
    if detected_vaults:
        choices = [questionary.Choice(v, value=v) for v in detected_vaults]
        choices.append(questionary.Choice("  [Custom input]", value="_custom"))
        if existing_vault:
            choices.append(questionary.Choice("  [Keep current]", value="_keep"))

        vault = questionary.select("  Select Obsidian vault:", choices=choices).ask()

        if vault == "_keep":
            console.print(f"  ✓ Keeping vault: {existing_vault}")
            return
        elif vault == "_custom":
            vault = questionary.text(
                "  Vault name:",
                default=existing_vault or "",
            ).ask()
        # else: vault is the selected name
    else:
        vault = questionary.text(
            "  Vault name (or leave blank to skip):",
            default=existing_vault or "",
        ).ask()

    vault = (vault or "").strip()
    if vault:
        _save("obsidian_vault", vault)
        console.print(f"  ✓ Obsidian vault: {vault}")
        # Verify connection
        if cli_path:
            _verify_obsidian_vault(cli_path, vault)
    else:
        _save("obsidian_vault", "")
        console.print("  [yellow]⚠ No vault configured. Obsidian tool will be active but may return errors.[/yellow]")
        console.print("  [dim]Set later: openlama config obsidian[/dim]")


def _verify_obsidian_vault(cli_path: str, vault: str):
    """Verify obsidian-cli can access the configured vault."""
    try:
        # Set default vault
        result = subprocess.run(
            [cli_path, "set-default", vault],
            capture_output=True, text=True, timeout=10,
        )
        # Try listing vault contents
        result = subprocess.run(
            [cli_path, "list", "-v", vault],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            console.print(f"  [green]✓ Vault connected: {len(lines)} items found[/green]")
        else:
            err = result.stderr.strip()
            console.print(f"  [yellow]⚠ Vault access issue: {err[:100]}[/yellow]")
            console.print("  [dim]Check vault name matches exactly (case-sensitive)[/dim]")
    except Exception as e:
        console.print(f"  [yellow]⚠ Could not verify vault: {e}[/yellow]")


def _install_obsidian_cli() -> bool:
    """Install obsidian-cli. Supports brew (macOS/Linux) and go install."""
    brew = shutil.which("brew")

    if brew:
        try:
            # Add tap and install
            result = subprocess.run(
                [brew, "tap", "yakitrak/yakitrak"],
                capture_output=True, timeout=60,
            )
            result = subprocess.run(
                [brew, "install", "obsidian-cli"],
                capture_output=True, timeout=120,
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Fallback: go install
    go = shutil.which("go")
    if go:
        try:
            console.print("  [dim]Trying: go install...[/dim]")
            result = subprocess.run(
                [go, "install", "github.com/Yakitrak/obsidian-cli@latest"],
                capture_output=True, timeout=120,
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return False


def _detect_obsidian_vaults() -> list[str]:
    """Try to detect Obsidian vault names from obsidian-cli or filesystem."""
    # Method 1: obsidian-cli list-vaults (if installed)
    if shutil.which("obsidian-cli"):
        try:
            result = subprocess.run(
                ["obsidian-cli", "list-vaults"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                vaults = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
                if vaults:
                    return vaults
        except Exception:
            pass

    # Method 2: Check Obsidian config file (platform-specific paths)
    candidates = []
    if sys.platform == "darwin":
        candidates.append(Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json")
    elif sys.platform == "win32":
        appdata = Path.home() / "AppData" / "Roaming" / "obsidian" / "obsidian.json"
        candidates.append(appdata)
    candidates.append(Path.home() / ".config" / "obsidian" / "obsidian.json")  # Linux / fallback

    for obsidian_config in candidates:
        if not obsidian_config.exists():
            continue
        try:
            import json
            data = json.loads(obsidian_config.read_text(encoding="utf-8"))
            vaults = data.get("vaults", {})
            return [Path(v.get("path", "")).name for v in vaults.values() if v.get("path")]
        except Exception:
            pass

    return []


def _pip_install(package: str) -> bool:
    """Install a pip package into the current Python environment."""
    python = sys.executable
    uv = shutil.which("uv")

    # Order: uv (targeting this env) → pip module → pip3
    methods = []
    if uv:
        methods.append([uv, "pip", "install", "--python", python, package])
    methods.append([python, "-m", "pip", "install", package])
    if shutil.which("pip3"):
        methods.append(["pip3", "install", "--target",
                        str(Path(python).parent.parent / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"),
                        package])

    for cmd in methods:
        try:
            console.print(f"  [dim]Trying: {' '.join(cmd[:4])}...[/dim]")
            result = subprocess.run(cmd, capture_output=True, timeout=300)
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue

    console.print("  [red]✗ Installation failed[/red]")
    return False
