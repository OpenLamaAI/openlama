"""Structured logging for openlama."""
import logging
import sys
from pathlib import Path


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
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # File handler (for daemon mode)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    return logger


def get_logger(module: str = "") -> logging.Logger:
    """Get a child logger for a module."""
    base = "openlama"
    return logging.getLogger(f"{base}.{module}" if module else base)
