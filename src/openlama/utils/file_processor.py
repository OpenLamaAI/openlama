"""File processing – PDF, text, audio, video to model-friendly formats."""

from __future__ import annotations

import base64
import io
import mimetypes
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from openlama.config import get_config_int


def detect_file_type(mime_type: Optional[str], filename: Optional[str]) -> str:
    """Classify file into: image, pdf, text, audio, video, unknown."""
    mime = (mime_type or "").lower()
    name = (filename or "").lower()

    if mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff")):
        return "image"
    if mime == "application/pdf" or name.endswith(".pdf"):
        return "pdf"
    if mime.startswith("audio/") or name.endswith((".mp3", ".ogg", ".wav", ".flac", ".m4a", ".opus")):
        return "audio"
    if mime.startswith("video/") or name.endswith((".mp4", ".avi", ".mkv", ".mov", ".webm")):
        return "video"

    text_mimes = ("text/", "application/json", "application/xml", "application/javascript",
                  "application/x-python", "application/x-sh", "application/yaml")
    text_exts = (".txt", ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go", ".rs",
                 ".rb", ".php", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".toml",
                 ".ini", ".cfg", ".conf", ".sh", ".bash", ".zsh", ".md", ".rst", ".csv",
                 ".sql", ".log", ".env", ".dockerfile", ".makefile", ".gradle", ".kt", ".swift")
    if any(mime.startswith(t) for t in text_mimes) or any(name.endswith(e) for e in text_exts):
        return "text"

    return "unknown"


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
        # Render at 2x for readability
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
