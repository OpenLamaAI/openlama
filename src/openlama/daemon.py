"""Daemon management — PID file based."""
import os
import subprocess
import sys
import signal
import time
from pathlib import Path
from openlama.config import DATA_DIR, TERMUX

PID_FILE = DATA_DIR / "openlama.pid"
LOG_FILE = DATA_DIR / "openlama.log"


def _read_pid() -> int | None:
    """Read PID from PID file if the process is alive."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            PID_FILE.unlink(missing_ok=True)
    return None


def _find_running_process() -> int | None:
    """Find a running openlama process by scanning OS process list.

    Works across all platforms:
    - macOS/Linux: `ps aux` + grep
    - Windows: `tasklist` + findstr
    - Termux: same as Linux
    """
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "openlama" in line.lower():
                    # CSV: "python.exe","12345","Console","1","50,000 K"
                    parts = line.strip('"').split('","')
                    if len(parts) >= 2:
                        return int(parts[1])
        else:
            result = subprocess.run(
                ["ps", "ax", "-o", "pid,command"],
                capture_output=True, text=True, timeout=5,
            )
            my_pid = os.getpid()
            for line in result.stdout.splitlines():
                line = line.strip()
                if "openlama" not in line:
                    continue
                # Match: "openlama start" but not "openlama status/stop/logs/doctor"
                if "openlama start" not in line and "openlama.cli start" not in line:
                    continue
                # Exclude management commands that contain "start" in args
                if any(x in line for x in ("--install-service", "--uninstall-service", "status", "stop", "doctor")):
                    continue
                parts = line.split(None, 1)
                if parts:
                    pid = int(parts[0])
                    if pid != my_pid:
                        return pid
    except Exception:
        pass
    return None


def get_daemon_status() -> str:
    """Get openlama process status. Checks PID file first, then scans OS processes."""
    # 1. PID file (set by daemon mode -d)
    pid = _read_pid()
    if pid:
        return f"🟢 Running (PID {pid})"

    # 2. OS process scan (catches launchd/systemd/Termux:Boot foreground mode)
    pid = _find_running_process()
    if pid:
        return f"🟢 Running (PID {pid}, service)"

    return "🔴 Not running"


def _is_launchd_managed() -> bool:
    """Check if openlama is managed by launchd (macOS service)."""
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["launchctl", "list", "com.openlama.agent"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _is_systemd_managed() -> bool:
    """Check if openlama is managed by systemd."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "openlama"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def start_daemon():
    """Run bot in background (fork on Unix, subprocess on Windows)."""
    existing = _read_pid() or _find_running_process()
    if existing:
        print(f"openlama is already running (PID {existing})")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32" or TERMUX:
        # Windows / Termux: use subprocess (fork is unreliable on Android)
        log_fd = open(LOG_FILE, "a", encoding="utf-8")
        popen_kw: dict = {"start_new_session": True}
        if sys.platform == "win32":
            popen_kw = {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "openlama.cli", "start"],
                stdout=log_fd,
                stderr=log_fd,
                **popen_kw,
            )
            PID_FILE.write_text(str(proc.pid))
            print(f"🟢 openlama daemon started (PID {proc.pid})")
            print(f"   Logs: {LOG_FILE}")
            if TERMUX:
                # Acquire wake-lock to prevent Android from killing the process
                result = subprocess.run(
                    ["termux-wake-lock"], capture_output=True, timeout=5,
                )
                if result.returncode == 0:
                    print("   🔒 Wake lock acquired")
                else:
                    print("   ⚠ termux-wake-lock failed — process may be killed when screen is off")
                    print("     Install Termux:API app from F-Droid and run: pkg install termux-api")
                # Ensure wake-unlock on any exit (crash, OOM, SIGTERM)
                import atexit
                atexit.register(
                    lambda: subprocess.run(
                        ["termux-wake-unlock"], capture_output=True, timeout=5,
                    )
                )
        finally:
            log_fd.close()
        return

    # Unix (macOS/Linux desktop): fork
    pid = os.fork()
    if pid > 0:
        # Parent
        print(f"🟢 openlama daemon started (PID {pid})")
        print(f"   Logs: {LOG_FILE}")
        sys.exit(0)

    # Child — detach
    os.setsid()

    # Redirect stdout/stderr to log file
    log_fd = open(LOG_FILE, "a", encoding="utf-8")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())

    # Write PID file
    PID_FILE.write_text(str(os.getpid()))

    # Cleanup on exit
    import atexit
    atexit.register(lambda: PID_FILE.unlink(missing_ok=True))

    # Run bot
    from openlama.channels.telegram.bot import main as run_telegram
    try:
        run_telegram()
    finally:
        PID_FILE.unlink(missing_ok=True)


def stop_daemon():
    """Stop the daemon. Handles launchd/systemd gracefully."""
    # If managed by launchd, use launchctl to stop (prevents auto-restart)
    if _is_launchd_managed():
        pid = _find_running_process()
        subprocess.run(["launchctl", "stop", "com.openlama.agent"], capture_output=True, timeout=10)
        time.sleep(1)
        # launchctl stop + KeepAlive means it will restart — we need to unload
        # But we don't unload here (that would disable the service permanently)
        # Instead, stop just kills and lets launchd restart if KeepAlive
        if pid:
            print(f"🔴 openlama daemon stopped (was PID {pid})")
        else:
            print("🔴 openlama daemon stopped")
        PID_FILE.unlink(missing_ok=True)
        return

    if _is_systemd_managed():
        subprocess.run(["systemctl", "stop", "openlama"], capture_output=True, timeout=10)
        print("🔴 openlama daemon stopped (systemd)")
        PID_FILE.unlink(missing_ok=True)
        return

    pid = _read_pid()
    if not pid:
        pid = _find_running_process()
    if not pid:
        print("🔴 openlama is not running")
        return

    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        os.kill(pid, signal.SIGTERM)

    for _ in range(10):
        try:
            os.kill(pid, 0)
            time.sleep(0.5)
        except (ProcessLookupError, PermissionError, OSError):
            break

    PID_FILE.unlink(missing_ok=True)
    print(f"🔴 openlama daemon stopped (was PID {pid})")

    if TERMUX:
        subprocess.run(["termux-wake-unlock"], capture_output=True, timeout=5)


def restart_daemon():
    """Restart the daemon. Uses service manager when available."""
    if _is_launchd_managed():
        pid = _find_running_process()
        # kickstart -k = kill + restart in one atomic operation
        subprocess.run(
            ["launchctl", "kickstart", "-k", "gui/" + str(os.getuid()) + "/com.openlama.agent"],
            capture_output=True, timeout=15,
        )
        time.sleep(2)
        new_pid = _find_running_process()
        if pid:
            print(f"🔴 openlama daemon stopped (was PID {pid})")
        print(f"🟢 openlama daemon started (PID {new_pid or '?'})")
        print(f"   Logs: {LOG_FILE}")
        return

    if _is_systemd_managed():
        subprocess.run(["systemctl", "restart", "openlama"], capture_output=True, timeout=15)
        time.sleep(2)
        print("🟢 openlama daemon restarted (systemd)")
        return

    stop_daemon()
    time.sleep(1)
    start_daemon()


def tail_logs(last: int = 0, level: str = ""):
    """Show logs."""
    if not LOG_FILE.exists():
        print(f"No log file found at {LOG_FILE}")
        return

    lines = LOG_FILE.read_text(encoding="utf-8").splitlines()

    if level:
        lines = [l for l in lines if f"[{level.upper()}]" in l]

    if last > 0:
        lines = lines[-last:]

    for line in lines:
        print(line)

    if not last:
        # Live tail
        if sys.platform == "win32":
            # Windows: read and follow
            import time as _time
            last_pos = 0
            try:
                while True:
                    with open(LOG_FILE, encoding="utf-8") as f:
                        f.seek(last_pos)
                        new_lines = f.read()
                        if new_lines:
                            print(new_lines, end="")
                        last_pos = f.tell()
                    _time.sleep(1)
            except KeyboardInterrupt:
                pass
        else:
            import subprocess
            try:
                subprocess.run(["tail", "-f", str(LOG_FILE)])
            except KeyboardInterrupt:
                pass
