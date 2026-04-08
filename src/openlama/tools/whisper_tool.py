"""Tool: whisper — Audio/voice transcription using faster-whisper STT."""

from openlama.tools.registry import register_tool
from openlama.logger import get_logger

logger = get_logger("tool.whisper")


async def _execute(args: dict) -> str:
    file_path = args.get("file_path", "").strip()
    if not file_path:
        return "file_path is required (path to an audio file)."

    from pathlib import Path
    p = Path(file_path)
    if not p.exists():
        return f"File not found: {file_path}"

    try:
        from openlama.utils.file_processor import transcribe_audio
    except ImportError:
        return "STT not available. Install faster-whisper: pip install faster-whisper"

    file_bytes = p.read_bytes()
    result = transcribe_audio(file_bytes, p.name)
    return result


register_tool(
    name="whisper",
    description="Transcribe audio/voice files to text using speech-to-text (STT). Converts spoken language to written text.",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the audio file to transcribe (mp3, ogg, wav, m4a, etc.)",
            },
        },
        "required": ["file_path"],
    },
    execute=_execute,
)
