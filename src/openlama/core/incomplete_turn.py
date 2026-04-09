"""Incomplete turn & fabrication detection — ensures models use tools correctly.

Korean verb structure: [ACTION_STEM] + [SUFFIX]
- Planning suffixes: ~하겠습니다, ~할게요, ~해보겠, ~해드릴게요, etc.
- Fabrication suffixes: ~했습니다, ~해봤, ~한 결과, ~해본 결과, etc.

Covers two critical edge cases:
1. PLANNING WITHOUT ACTION: "검색하겠습니다" + no tool_calls → retry
2. FABRICATED RESULTS: "검색했습니다. 결과는..." + no tool_calls → retry
"""
from __future__ import annotations

import re

from openlama.logger import get_logger

logger = get_logger("incomplete_turn")

# ── Korean verb stems for tool-related actions ──

_KO_ACTION_STEMS = (
    "검색|확인|조회|계산|분석|실행|처리|측정|점검|수행"
)

_KO_COMPOUND_STEMS = (
    "찾아|알아|살펴|읽어|작성|가져와|가져|돌려|열어|써|적어"
)

# ── Planning patterns: model DESCRIBES what it will do ──

_PLANNING_RE = re.compile(
    r"(?:"
    # Korean: [action stem] + planning suffix
    # ~하겠습니다 / ~하겠어요 / ~할게요 / ~할 수 있습니다
    rf"(?:{_KO_ACTION_STEMS})(?:하겠습니다|하겠어요|할게요|할 수 있|해보겠|해드릴|해드리겠|해볼게)"
    # Korean: [compound stem] + planning suffix
    # ~보겠습니다 / ~볼게요 / ~드릴게요 / ~드리겠습니다
    rf"|(?:{_KO_COMPOUND_STEMS})(?:보겠|볼게|드릴게|드리겠|보겠습니다|볼게요|드릴게요|드리겠습니다)"
    # Korean: generic planning endings (catches any verb + these endings)
    r"|해드릴게요|해볼게요|해드리겠습니다|해보겠습니다"
    # Korean: wait/hold phrases (implies about to do something)
    r"|잠시만요|잠깐만요|잠시만 기다|잠깐만 기다|기다려주세요|기다려 주세요"
    # English planning phrases
    r"|i(?:'ll| will) (?:search|check|look|find|calculate|run|fetch|read|write|get)"
    r"|let me (?:search|check|look|find|calculate|run|fetch|read|write|get)"
    r"|i(?:'m| am) going to"
    r"|i can do that"
    r"|i'll do that"
    r"|let me do that"
    r")",
    re.IGNORECASE,
)

# ── Fabrication patterns: model CLAIMS it used a tool but didn't ──

_FABRICATION_RE = re.compile(
    r"(?:"
    # Korean: [action stem] + past/result suffix
    # ~했습니다 / ~한 결과 / ~해봤 / ~해본 결과
    rf"(?:{_KO_ACTION_STEMS})(?:했습니다|했어요|한 결과|해봤|해본 결과|해 보았)"
    # Korean: [compound stem] + past suffix
    # ~봤습니다 / ~본 결과 / ~봤는데 / ~왔습니다
    rf"|(?:{_KO_COMPOUND_STEMS})(?:봤습니다|봤어요|봤는데|본 결과|왔습니다|왔어요)"
    # Korean: result-presenting patterns
    r"|검색 결과|조회 결과|계산 결과|분석 결과|실행 결과|처리 결과|측정 결과"
    r"|파일 내용|파일을 읽었|읽어본 결과"
    r"|다음은.*결과|결과를 알려드립니다|결과입니다"
    # English: claims to have performed tool actions
    r"|(?:i |i've |i have )(?:searched|checked|looked up|found|calculated|fetched|read the file|ran|executed)"
    r"|search results? (?:show|indicate|reveal)"
    r"|according to (?:my |the )(?:search|check|calculation|analysis)"
    r"|the (?:search|query|lookup) (?:returned|shows|found)"
    r"|after (?:searching|checking|looking|reading|running)"
    r")",
    re.IGNORECASE,
)

# ── Retry instructions ──

RETRY_INSTRUCTION = (
    "Your previous response only described a plan but did NOT call any tool. "
    "Do not restate the plan. CALL THE APPROPRIATE TOOL NOW. "
    "If you cannot determine which tool to use, state the exact issue in one sentence."
)

FABRICATION_INSTRUCTION = (
    "Your previous response claimed to have results from a tool, but you did NOT actually "
    "call any tool. This is fabrication. You MUST call the actual tool to get real results. "
    "CALL THE APPROPRIATE TOOL NOW. Do NOT make up results."
)

MAX_RETRIES = 2


def is_incomplete_turn(content: str, has_tool_calls: bool) -> bool:
    """Check if the model's response is planning-only without executing.

    Returns True if the response contains planning phrases but no tool calls.
    Does NOT check for fabrication (use is_fabricated_result for that).
    """
    if has_tool_calls:
        return False
    if not content:
        return False
    if len(content) > 700:
        return False
    if "```" in content:
        return False

    # Check for fabrication first — handled separately by is_fabricated_result
    if _FABRICATION_RE.search(content):
        return False

    if _PLANNING_RE.search(content):
        logger.info("incomplete turn detected: %s", content[:100])
        return True

    return False


def is_fabricated_result(content: str, has_tool_calls: bool) -> bool:
    """Check if the model fabricated tool results without actually calling tools.

    Catches: "검색 결과는..." or "I searched and found..." with tool_calls=[].
    """
    if has_tool_calls:
        return False
    if not content:
        return False

    if _FABRICATION_RE.search(content):
        logger.warning("fabricated tool result detected: %s", content[:150])
        return True

    return False
