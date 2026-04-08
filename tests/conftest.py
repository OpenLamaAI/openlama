"""Shared fixtures for all tests."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root and src/openlama are importable
_project_root = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _project_root)
sys.path.insert(0, str(Path(_project_root) / "src"))

# Set minimal env vars before any config import
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
os.environ.setdefault("BOT_ADMIN_PASSWORD", "test_password_12345")
os.environ.setdefault("BOT_DB_PATH", str(Path(tempfile.mkdtemp()) / "test.db"))
os.environ.setdefault("TOOL_SANDBOX_ENABLED", "false")


@pytest.fixture(autouse=True)
def _temp_db(tmp_path):
    """Use a fresh temp DB for each test."""
    db_path = tmp_path / "test.db"
    os.environ["BOT_DB_PATH"] = str(db_path)
    # Force config to re-read
    import config
    config.DB_PATH = db_path
    from database import init_db
    init_db()
    yield db_path


@pytest.fixture
def upload_dir(tmp_path):
    """Temp upload directory."""
    d = tmp_path / "uploads"
    d.mkdir()
    import config
    config.UPLOAD_TEMP_DIR = str(d)
    return d
