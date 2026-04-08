"""File processing – PDF, text, audio, video, archive to model-friendly formats."""

from __future__ import annotations

import base64
import io
import mimetypes
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from openlama.config import get_config_int
from openlama.logger import get_logger

logger = get_logger("file_processor")


def detect_file_type(mime_type: Optional[str], filename: Optional[str]) -> str:
    """Classify file into: image, pdf, text, audio, video, archive, unknown."""
    mime = (mime_type or "").lower()
    name = (filename or "").lower()

    if mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff")):
        return "image"
    if mime == "application/pdf" or name.endswith(".pdf"):
        return "pdf"
    if mime.startswith("audio/") or name.endswith((".mp3", ".ogg", ".wav", ".flac", ".m4a", ".opus", ".aac", ".wma")):
        return "audio"
    if mime.startswith("video/") or name.endswith((".mp4", ".avi", ".mkv", ".mov", ".webm")):
        return "video"

    archive_mimes = ("application/zip", "application/x-zip-compressed",
                     "application/x-tar", "application/gzip", "application/x-gzip",
                     "application/x-7z-compressed", "application/vnd.rar",
                     "application/x-rar-compressed")
    archive_exts = (".zip", ".tar", ".gz", ".tar.gz", ".tgz", ".rar", ".7z")
    if mime in archive_mimes or any(name.endswith(e) for e in archive_exts):
        return "archive"

    text_mimes = ("text/", "application/json", "application/xml", "application/javascript",
                  "application/x-python", "application/x-sh", "application/yaml")
    text_exts = (".txt", ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go", ".rs",
                 ".rb", ".php", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".toml",
                 ".ini", ".cfg", ".conf", ".sh", ".bash", ".zsh", ".md", ".rst", ".csv",
                 ".sql", ".log", ".env", ".dockerfile", ".makefile", ".gradle", ".kt", ".swift")
    if any(mime.startswith(t) for t in text_mimes) or any(name.endswith(e) for e in text_exts):
        return "text"

    return "unknown"


def is_binary(data: bytes, sample_size: int = 8192) -> bool:
    """Check if data looks like binary (contains null bytes or high ratio of non-text bytes)."""
    sample = data[:sample_size]
    if b"\x00" in sample:
        return True
    non_text = sum(1 for b in sample if b < 8 or (14 <= b < 32 and b != 27))
    return non_text / max(len(sample), 1) > 0.3


def process_pdf(file_bytes: bytes, max_pages: int = 20) -> list[str]:
    """Convert PDF pages to base64 PNG images using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []

    images: list[str] = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_bytes = pix.tobytes("png")
        images.append(base64.b64encode(img_bytes).decode("utf-8"))
    doc.close()
    return images


def process_text_file(file_bytes: bytes, filename: str = "") -> str:
    """Decode text/code file and return content string."""
    max_chars = get_config_int("max_file_read_chars", 50000)

    for encoding in ("utf-8", "euc-kr", "cp949", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        text = file_bytes.decode("utf-8", errors="replace")

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... (truncated, total {len(file_bytes)} bytes)"

    ext = Path(filename).suffix.lstrip(".") if filename else ""
    return f"```{ext}\n{text}\n```"


def process_audio(file_bytes: bytes) -> str:
    """Return base64-encoded audio."""
    return base64.b64encode(file_bytes).decode("utf-8")


def transcribe_audio(file_bytes: bytes, filename: str = "audio.ogg") -> str:
    """Transcribe audio using faster-whisper STT. Returns text."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return "[Audio transcription unavailable — install faster-whisper: pip install faster-whisper]"

    # Write to temp file (faster-whisper needs a file path)
    suffix = Path(filename).suffix or ".ogg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, info = model.transcribe(tmp_path, beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments)
        lang = info.language
        logger.info("STT: %d chars, lang=%s, duration=%.1fs", len(text), lang, info.duration)
        return text if text.strip() else "[No speech detected in audio]"
    except Exception as e:
        logger.error("STT error: %s", e)
        return f"[Audio transcription failed: {e}]"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def extract_archive(file_bytes: bytes, filename: str = "archive.zip") -> tuple[str, Path | None]:
    """Extract a ZIP archive to a temp directory.

    Returns (status_message, extracted_dir_path or None).
    Only ZIP is supported currently.
    """
    name_lower = filename.lower()
    if not name_lower.endswith(".zip"):
        return "Only ZIP archives are currently supported.", None

    try:
        with tempfile.TemporaryDirectory(prefix="openlama_archive_") as tmp_dir:
            tmp_path = Path(tmp_dir)

            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                # Security: check for path traversal
                for member in zf.namelist():
                    member_path = Path(member)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        return f"Archive contains unsafe path: {member}", None

                zf.extractall(tmp_path)

            # Return persistent copy (caller is responsible for cleanup)
            persist_dir = Path(tempfile.mkdtemp(prefix="openlama_extracted_"))
            shutil.copytree(tmp_path, persist_dir, dirs_exist_ok=True)
            return "ok", persist_dir

    except zipfile.BadZipFile:
        return "Invalid or corrupted ZIP file.", None
    except Exception as e:
        return f"Archive extraction failed: {e}", None


def process_video(file_bytes: bytes, max_frames: int = 10, fps: float = 0.5) -> list[str]:
    """Extract frames from video using ffmpeg, return base64 PNGs."""
    images: list[str] = []
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_video:
            tmp_video.write(file_bytes)
            tmp_path = tmp_video.name

        with tempfile.TemporaryDirectory() as tmp_dir:
            subprocess.run(
                [
                    "ffmpeg", "-i", tmp_path,
                    "-vf", f"fps={fps}",
                    "-frames:v", str(max_frames),
                    "-q:v", "2",
                    str(Path(tmp_dir) / "frame_%04d.png"),
                ],
                capture_output=True,
                timeout=30,
            )

            for frame_path in sorted(Path(tmp_dir).glob("frame_*.png")):
                img_bytes = frame_path.read_bytes()
                images.append(base64.b64encode(img_bytes).decode("utf-8"))

        Path(tmp_path).unlink(missing_ok=True)
    except Exception:
        pass
    return images
