"""OS service registration — launchd (macOS) / systemd (Linux) / Termux:Boot (Android)."""
import sys
import shutil
import subprocess
from pathlib import Path
from openlama.config import DATA_DIR, TERMUX

def _find_openlama_bin() -> str:
    path = shutil.which("openlama")
    return path or sys.executable + " -m openlama.cli"

def install():
    """Register as OS service."""
    if sys.platform == "darwin":
        _install_launchd()
    elif TERMUX:
        _install_termux()
    elif sys.platform == "linux":
        _install_systemd()
    elif sys.platform == "win32":
        _install_windows()
    else:
        print(f"Unsupported platform: {sys.platform}")

def uninstall():
    """Remove OS service."""
    if sys.platform == "darwin":
        _uninstall_launchd()
    elif TERMUX:
        _uninstall_termux()
    elif sys.platform == "linux":
        _uninstall_systemd()
    elif sys.platform == "win32":
        _uninstall_windows()

def _install_windows():
    bin_path = _find_openlama_bin()
    task_name = "openlama"
    subprocess.run([
        "schtasks", "/create",
        "/tn", task_name,
        "/tr", f'"{bin_path}" start',
        "/sc", "onlogon",
        "/rl", "highest",
        "/f",
    ])
    print(f"✅ Service registered via Task Scheduler: {task_name}")
    print("   openlama will start on logon")

def _uninstall_windows():
    subprocess.run(["schtasks", "/delete", "/tn", "openlama", "/f"])
    print("🗑 Task Scheduler entry removed")
    print("   Note: If openlama is currently running, stop it with 'openlama stop'")

def _install_launchd():
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist = plist_dir / "com.openlama.agent.plist"
    bin_path = _find_openlama_bin()
    log = str(DATA_DIR / "openlama.log")

    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openlama.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{bin_path}</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
</dict>
</plist>"""

    plist.write_text(content)
    subprocess.run(["launchctl", "load", str(plist)])
    print(f"✅ Service registered: {plist}")
    print("   openlama will start on login")

def _uninstall_launchd():
    plist = Path.home() / "Library" / "LaunchAgents" / "com.openlama.agent.plist"
    if plist.exists():
        subprocess.run(["launchctl", "unload", str(plist)])
        plist.unlink()
        print("🗑 Service removed")
    else:
        print("No service found")

def _install_systemd():
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = unit_dir / "openlama.service"
    bin_path = _find_openlama_bin()

    content = f"""[Unit]
Description=openlama — Personal AI Agent Bot
After=network.target

[Service]
ExecStart={bin_path} start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""

    unit.write_text(content)
    subprocess.run(["systemctl", "--user", "enable", "openlama"])
    subprocess.run(["systemctl", "--user", "start", "openlama"])
    print(f"✅ Service registered: {unit}")
    print("   openlama will start on boot")

def _uninstall_systemd():
    unit = Path.home() / ".config" / "systemd" / "user" / "openlama.service"
    if unit.exists():
        subprocess.run(["systemctl", "--user", "stop", "openlama"])
        subprocess.run(["systemctl", "--user", "disable", "openlama"])
        unit.unlink()
        print("🗑 Service removed")
    else:
        print("No service found")

def _install_termux():
    """Create Termux:Boot auto-start script."""
    boot_dir = Path.home() / ".termux" / "boot"
    boot_dir.mkdir(parents=True, exist_ok=True)
    bin_path = _find_openlama_bin()
    log = str(DATA_DIR / "openlama.log")
    from openlama.config import is_ollama_remote

    script = boot_dir / "start-openlama.sh"
    lines = [
        "#!/data/data/com.termux/files/usr/bin/bash",
        "# openlama auto-start script (Termux:Boot)",
        "termux-wake-lock",
    ]
    if not is_ollama_remote():
        lines += [
            "ollama serve > /dev/null 2>&1 &",
            "sleep 3",
        ]
    lines.append(f"{bin_path} start >> {log} 2>&1 &")

    script.write_text("\n".join(lines) + "\n")
    script.chmod(0o755)
    print(f"✅ Termux:Boot script created: {script}")
    print("   openlama will start on device boot")
    print("   ⚠ Requires Termux:Boot app from F-Droid")

def _uninstall_termux():
    script = Path.home() / ".termux" / "boot" / "start-openlama.sh"
    if script.exists():
        script.unlink()
        print("🗑 Termux:Boot script removed")
        print("   Note: If openlama is currently running, stop it with 'openlama stop'")
    else:
        print("No boot script found")
