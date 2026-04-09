"""Tests for incomplete turn & fabrication detection.

Two edge cases covered:
1. Model plans but doesn't call tools ("검색해드릴게요" → no tool_calls)
2. Model fabricates tool results ("검색 결과는..." → no tool_calls)
"""

import pytest

from openlama.core.incomplete_turn import (
    is_incomplete_turn,
    is_fabricated_result,
    RETRY_INSTRUCTION,
    FABRICATION_INSTRUCTION,
    _PLANNING_RE,
    _FABRICATION_RE,
)


# ══════════════════════════════════════════════════
# EDGE CASE 1: Planning without action
# ══════════════════════════════════════════════════


@pytest.mark.parametrize("text", [
    # ~하겠습니다 (formal future)
    "검색하겠습니다", "확인하겠습니다", "계산하겠습니다",
    "조회하겠습니다", "분석하겠습니다", "실행하겠습니다", "처리하겠습니다",
    # ~할게요 (casual future)
    "검색할게요", "확인할게요", "계산할게요",
    # ~해보겠/해드릴 compound
    "검색해보겠습니다", "확인해드릴게요", "살펴보겠습니다",
    "찾아보겠습니다", "알아보겠습니다", "읽어보겠습니다",
    "작성해드릴게요", "가져와드릴게요",
    # Wait/hold phrases
    "잠시만요", "잠깐만요", "기다려주세요",
    # In-sentence context
    "네, 검색하겠습니다.", "바로 확인해드릴게요.", "잠시만요, 조회할게요.",
    "웹에서 확인해보겠습니다.", "파일을 읽어보겠습니다.",
])
def test_korean_planning_detected(text):
    """Korean planning phrases without tool calls should be flagged."""
    assert is_incomplete_turn(text, has_tool_calls=False) is True


@pytest.mark.parametrize("text", [
    "I'll search for that.",
    "Let me check that for you.",
    "I will find the information.",
    "Let me look into that.",
    "I'll calculate that.",
    "I'm going to fetch the data.",
    "I can do that for you.",
    "Let me run that command.",
])
def test_english_planning_detected(text):
    """English planning phrases without tool calls should be flagged."""
    assert is_incomplete_turn(text, has_tool_calls=False) is True


def test_planning_not_flagged_with_tool_calls():
    assert is_incomplete_turn("I'll search for that.", has_tool_calls=True) is False


def test_planning_not_flagged_empty():
    assert is_incomplete_turn("", has_tool_calls=False) is False


def test_planning_not_flagged_long_response():
    long_text = "확인해보겠습니다. " + "a" * 700
    assert is_incomplete_turn(long_text, has_tool_calls=False) is False


def test_planning_not_flagged_code_block():
    text = "확인해보겠습니다.\n```python\nprint('hello')\n```"
    assert is_incomplete_turn(text, has_tool_calls=False) is False


def test_planning_not_flagged_normal_answer():
    assert is_incomplete_turn("The capital of France is Paris.", has_tool_calls=False) is False
    assert is_incomplete_turn("네, 맞습니다.", has_tool_calls=False) is False


# ══════════════════════════════════════════════════
# EDGE CASE 2: Fabricated tool results (HALLUCINATION)
# ══════════════════════════════════════════════════


@pytest.mark.parametrize("text", [
    # Korean: ~했습니다 (past formal - claims completed action)
    "검색했습니다. 결과는 다음과 같습니다.",
    "확인했습니다. 서버가 정상입니다.",
    "조회했습니다. 3개의 프로세스입니다.",
    "계산했습니다. 결과는 42입니다.",
    "분석했습니다. 문제 없습니다.",
    "실행했습니다. 성공입니다.",
    "처리했습니다. 완료되었습니다.",
    # Korean: ~한 결과 / ~해본 결과 / ~해봤
    "검색한 결과, 해당 정보를 찾았습니다.",
    "확인해본 결과, 서버가 정상 작동 중입니다.",
    "검색해봤는데 관련 내용이 있습니다.",
    "확인해봤는데 파일이 존재합니다.",
    # Korean: compound stems (찾아/알아/살펴/읽어)
    "찾아봤습니다. 결과는 다음과 같습니다.",
    "찾아본 결과 문제가 없습니다.",
    "알아봤는데 정상입니다.",
    "알아본 결과 3개입니다.",
    "살펴봤습니다. 이상 없습니다.",
    "살펴본 결과 정상입니다.",
    "읽어봤는데 설정이 맞습니다.",
    # Korean: result patterns
    "검색 결과는 다음과 같습니다: Python asyncio는 비동기 라이브러리입니다.",
    "파일 내용은 다음과 같습니다.",
    "계산 결과는 42입니다.",
    "조회 결과, 3개의 프로세스가 실행 중입니다.",
    "실행 결과, 정상적으로 완료되었습니다.",
    "다음은 검색 결과입니다.",
    # English: model claims it searched
    "I searched and found that Python 3.12 is the latest version.",
    "Search results show that the package is available.",
    "According to my search, the API endpoint is /v2/users.",
    "After searching, I found the answer.",
    # English: model claims it checked/read/ran
    "I checked and the server is running.",
    "I read the file and it contains the config.",
    "I ran the command and it returned success.",
    "After checking, the process is active.",
    "I've searched for the information and found it.",
])
def test_fabrication_detected(text):
    """Model claims tool results without tool_calls → fabrication."""
    assert is_fabricated_result(text, has_tool_calls=False) is True, \
        f"Should detect fabrication: {text[:50]}"


@pytest.mark.parametrize("text", [
    # Korean: same phrases but WITH tool_calls are legitimate
    "검색 결과는 다음과 같습니다: Python asyncio는 비동기 라이브러리입니다.",
    "확인해본 결과, 서버가 정상 작동 중입니다.",
    "계산 결과는 42입니다.",
    # English
    "I searched and found that Python 3.12 is the latest version.",
    "I checked and the server is running.",
])
def test_fabrication_not_flagged_with_tool_calls(text):
    """Same phrases WITH tool_calls are legitimate — not fabrication."""
    assert is_fabricated_result(text, has_tool_calls=True) is False


def test_fabrication_not_flagged_empty():
    assert is_fabricated_result("", has_tool_calls=False) is False


def test_fabrication_not_flagged_general_knowledge():
    """General knowledge answers should not be flagged as fabrication."""
    assert is_fabricated_result("Python은 프로그래밍 언어입니다.", has_tool_calls=False) is False
    assert is_fabricated_result("The answer is 42.", has_tool_calls=False) is False
    assert is_fabricated_result("네, 맞습니다.", has_tool_calls=False) is False
    assert is_fabricated_result("서울의 날씨는 보통 온화합니다.", has_tool_calls=False) is False


# ══════════════════════════════════════════════════
# Interaction: planning vs fabrication priority
# ══════════════════════════════════════════════════


def test_fabrication_takes_priority_over_planning():
    """If response has BOTH fabrication AND planning patterns,
    is_incomplete_turn should return False (let fabrication handler take over)."""
    # This text has a fabrication claim
    text = "검색 결과는 다음과 같습니다."
    # is_incomplete_turn should NOT flag it (fabrication is handled separately)
    assert is_incomplete_turn(text, has_tool_calls=False) is False
    # is_fabricated_result SHOULD flag it
    assert is_fabricated_result(text, has_tool_calls=False) is True


def test_only_planning_no_fabrication():
    """Pure planning without fabrication claim."""
    text = "검색해드릴게요"
    assert is_incomplete_turn(text, has_tool_calls=False) is True
    assert is_fabricated_result(text, has_tool_calls=False) is False


def test_neither_planning_nor_fabrication():
    """Normal answer — neither detection should fire."""
    text = "안녕하세요. 무엇을 도와드릴까요?"
    assert is_incomplete_turn(text, has_tool_calls=False) is False
    assert is_fabricated_result(text, has_tool_calls=False) is False


# ══════════════════════════════════════════════════
# Regex validation
# ══════════════════════════════════════════════════


def test_planning_regex_matches():
    assert _PLANNING_RE.search("해드릴게요") is not None
    assert _PLANNING_RE.search("I'll search for that") is not None
    assert _PLANNING_RE.search("Let me check") is not None


def test_planning_regex_no_match():
    assert _PLANNING_RE.search("The answer is 42.") is None
    assert _PLANNING_RE.search("Hello world") is None


def test_fabrication_regex_korean_past_form():
    """All Korean action stems + past suffix should match."""
    for stem in ["검색", "확인", "조회", "계산", "분석", "실행", "처리"]:
        assert _FABRICATION_RE.search(f"{stem}했습니다") is not None, f"{stem}했습니다 not matched"
        assert _FABRICATION_RE.search(f"{stem}한 결과") is not None, f"{stem}한 결과 not matched"


def test_fabrication_regex_korean_compound_past():
    """Compound stems + past suffix should match."""
    for stem in ["찾아", "알아", "살펴"]:
        assert _FABRICATION_RE.search(f"{stem}봤습니다") is not None, f"{stem}봤습니다 not matched"
        assert _FABRICATION_RE.search(f"{stem}본 결과") is not None, f"{stem}본 결과 not matched"


def test_fabrication_regex_english():
    assert _FABRICATION_RE.search("I searched and found") is not None
    assert _FABRICATION_RE.search("After searching, I found") is not None
    assert _FABRICATION_RE.search("I checked and the server") is not None


def test_fabrication_regex_no_match():
    assert _FABRICATION_RE.search("Hello world") is None
    assert _FABRICATION_RE.search("Python은 좋은 언어입니다") is None
    assert _FABRICATION_RE.search("네, 맞습니다") is None
    assert _FABRICATION_RE.search("감사합니다") is None


# ══════════════════════════════════════════════════
# Instruction content validation
# ══════════════════════════════════════════════════


def test_retry_instruction():
    assert "CALL" in RETRY_INSTRUCTION
    assert "tool" in RETRY_INSTRUCTION.lower()


def test_fabrication_instruction():
    assert "CALL" in FABRICATION_INSTRUCTION
    assert "fabrication" in FABRICATION_INSTRUCTION.lower()
    assert "NOT" in FABRICATION_INSTRUCTION
