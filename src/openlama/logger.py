"""Structured logging for openlama with request correlation ID support."""
import contextvars
import logging
import sys
import uuid
from pathlib import Path

# Context variable for request correlation ID — propagated across async calls
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def set_request_id(request_id: str | None = None) -> str:
    """Set the current request correlation ID. Generates one if not provided."""
    rid = request_id or uuid.uuid4().hex[:8]
    _request_id.set(rid)
    return rid


def get_request_id() -> str:
    """Get the current request correlation ID."""
    return _request_id.get("")


class _RequestIdFilter(logging.Filter):
    """Inject request_id into all log records."""
    def filter(self, record):
        record.request_id = _request_id.get("")
        return True


def setup_logger(
    log_file: Path | None = None,
    level: str = "INFO",
    name: str = "openlama",
) -> logging.Logger:
    """Configure structured logging — console + optional file."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # Already configured

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False  # Prevent duplicate logs from parent loggers
    # Include request_id in format when available
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Add filter that injects request_id
    rid_filter = _RequestIdFilter()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.addFilter(rid_filter)
    logger.addHandler(console)

    # File handler (for daemon mode)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.addFilter(rid_filter)
        logger.addHandler(file_handler)

    return logger


def get_logger(module: str = "") -> logging.Logger:
    """Get a child logger for a module."""
    base = "openlama"
    return logging.getLogger(f"{base}.{module}" if module else base)
