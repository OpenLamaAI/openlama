"""Tests for file processor – type detection, PDF, text, video processing."""

from utils.file_processor import detect_file_type, process_text_file


# ── detect_file_type ──

def test_detect_image_mime():
    assert detect_file_type("image/png", "photo.png") == "image"
    assert detect_file_type("image/jpeg", "photo.jpg") == "image"


def test_detect_image_ext():
    assert detect_file_type("", "file.png") == "image"
    assert detect_file_type("", "file.webp") == "image"


def test_detect_pdf():
    assert detect_file_type("application/pdf", "doc.pdf") == "pdf"
    assert detect_file_type("", "doc.pdf") == "pdf"


def test_detect_audio():
    assert detect_file_type("audio/mp3", "song.mp3") == "audio"
    assert detect_file_type("", "file.ogg") == "audio"
    assert detect_file_type("", "file.opus") == "audio"


def test_detect_video():
    assert detect_file_type("video/mp4", "clip.mp4") == "video"
    assert detect_file_type("", "file.mkv") == "video"


def test_detect_text():
    assert detect_file_type("text/plain", "readme.txt") == "text"
    assert detect_file_type("", "main.py") == "text"
    assert detect_file_type("", "config.json") == "text"
    assert detect_file_type("", "style.css") == "text"
    assert detect_file_type("application/json", "") == "text"


def test_detect_unknown():
    assert detect_file_type("application/octet-stream", "data.bin") == "unknown"
    assert detect_file_type("", "file.xyz") == "unknown"


# ── process_text_file ──

def test_process_text_utf8():
    content = "Hello World 안녕하세요"
    result = process_text_file(content.encode("utf-8"), "test.py")
    assert "Hello World" in result
    assert "안녕하세요" in result
    assert "```py" in result


def test_process_text_euckr():
    content = "한글 테스트"
    result = process_text_file(content.encode("euc-kr"), "test.txt")
    assert "한글 테스트" in result


def test_process_text_truncation():
    """Text exceeding MAX_FILE_READ_CHARS should be truncated."""
    from config import MAX_FILE_READ_CHARS
    content = "B" * (MAX_FILE_READ_CHARS + 1000)
    result = process_text_file(content.encode("utf-8"), "big.txt")
    assert "truncated" in result
    assert result.count("B") <= MAX_FILE_READ_CHARS + 10
