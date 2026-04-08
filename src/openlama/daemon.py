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
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            # Check if process is alive
            os.kill(pid, 0)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            PID_FILE.unlink(missing_ok=True)
    return None


def get_daemon_status() -> str:
    pid = _read_pid()
    if pid:
        return f"🟢 Running (PID {pid})"
    return "🔴 Not running"


def start_daemon():
    """Run bot in background (fork on Unix, subprocess on Windows)."""
    existing = _read_pid()
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
    """Stop the daemon."""
    pid = _read_pid()
    if not pid:
        print("🔴 openlama is not running")
        return

    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        os.kill(pid, signal.SIGTERM)

    # Wait for process to exit
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
    """Restart the daemon."""
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
