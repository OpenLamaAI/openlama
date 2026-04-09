"""Tool call loop detection — prevents runaway identical tool calling.

Detects three patterns:
1. generic_repeat: Same tool called with identical arguments repeatedly
2. no_progress: Same tool + args producing identical results
3. ping_pong: Alternating A-B-A-B tool call pattern

Thresholds are aggressive (5/10) since small models are more prone to loops.
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass

from openlama.logger import get_logger

logger = get_logger("tool_loop")

HISTORY_SIZE = 30
WARNING_THRESHOLD = 5
CRITICAL_THRESHOLD = 10


@dataclass
class ToolCallRecord:
    tool_name: str
    call_hash: str   # tool_name + sha256(args)
    result_hash: str  # sha256(result[:500])


def _hash(obj) -> str:
    """Create short hash of an object for comparison."""
    if isinstance(obj, dict):
        s = json.dumps(obj, sort_keys=True, default=str)
    else:
        s = str(obj)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _count_ping_pong(history: list[ToolCallRecord]) -> int:
    """Count consecutive alternating A-B-A-B patterns from end of history.

    Only counts if the last 4 entries form A-B-A-B with the same A and B hashes.
    """
    if len(history) < 4:
        return 0
    a_hash = history[-2].call_hash
    b_hash = history[-1].call_hash
    # Must be two DIFFERENT tools
    if a_hash == b_hash:
        return 0
    # Walk backward counting complete A-B pairs
    count = 0
    i = len(history) - 1
    while i >= 1:
        if history[i].call_hash == b_hash and history[i - 1].call_hash == a_hash:
            count += 1
            i -= 2
        else:
            break
    return count


class LoopDetector:
    """Detect and report tool calling loops.

    Usage:
        detector = LoopDetector()
        for each tool call:
            warning = detector.record(name, args, result)
            if warning and "CRITICAL" in warning:
                break  # stop the loop
    """

    def __init__(self):
        self._history: deque[ToolCallRecord] = deque(maxlen=HISTORY_SIZE)

    def record(self, tool_name: str, args: dict, result: str) -> str | None:
        """Record a tool call and check for loop patterns.

        Returns:
            Warning/critical message string if loop detected, None otherwise.
        """
        call_hash = f"{tool_name}:{_hash(args)}"
        result_hash = _hash(result[:500])
        record = ToolCallRecord(
            tool_name=tool_name,
            call_hash=call_hash,
            result_hash=result_hash,
        )
        self._history.append(record)

        # 1. Check: same call repeated (generic_repeat)
        same_call_count = sum(1 for r in self._history if r.call_hash == call_hash)

        if same_call_count >= CRITICAL_THRESHOLD:
            msg = (
                f"CRITICAL: {tool_name} called {same_call_count} times with identical "
                f"arguments. Stop and report the result to the user."
            )
            logger.warning(msg)
            return msg

        if same_call_count >= WARNING_THRESHOLD:
            # Check no-progress: same call AND same result
            no_progress_count = sum(
                1 for r in self._history
                if r.call_hash == call_hash and r.result_hash == result_hash
            )
            if no_progress_count >= WARNING_THRESHOLD:
                msg = (
                    f"WARNING: {tool_name} called {no_progress_count} times with identical "
                    f"arguments and no progress. Try a different approach or report failure."
                )
                logger.warning(msg)
                return msg

        # 2. Check: ping-pong (A-B-A-B alternation)
        if len(self._history) >= 4:
            pp_count = _count_ping_pong(list(self._history))
            if pp_count >= CRITICAL_THRESHOLD:
                a_name = self._history[-2].tool_name
                b_name = self._history[-1].tool_name
                msg = (
                    f"CRITICAL: Detected alternating loop between {a_name} and {b_name} "
                    f"({pp_count} rounds). Stop and report to user."
                )
                logger.warning(msg)
                return msg
            if pp_count >= WARNING_THRESHOLD:
                a_name = self._history[-2].tool_name
                b_name = self._history[-1].tool_name
                msg = (
                    f"WARNING: Detected alternating pattern between {a_name} and {b_name} "
                    f"({pp_count} rounds). Break the cycle — try a different approach."
                )
                logger.warning(msg)
                return msg

        return None

    def reset(self):
        """Clear history."""
        self._history.clear()
