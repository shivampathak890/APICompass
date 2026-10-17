"""SQLite database connection management and path resolution for APICompass v3."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional, Union
import logging

from app.config import settings

logger = logging.getLogger("apicompass.db.connection")

# Root directory of the repository
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def get_db_path(db_path_override: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the SQLite database path predictably.

    Creates the parent directory if it does not exist.
    """
    if db_path_override:
        path = Path(db_path_override)
    else:
        configured = settings.APICOMPASS_DB_PATH
        path = Path(configured)

    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    else:
        path = path.resolve()

    # Ensure parent directory exists (unless in-memory)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    return path


@contextmanager
def get_db(db_path_override: Optional[Union[str, Path]] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite database connections.

    Configures:
    - row_factory = sqlite3.Row for dict-like row access
    - PRAGMA foreign_keys = ON (enforced on every connection)
    - PRAGMA busy_timeout = configured timeout (default 5000ms)
    - PRAGMA journal_mode = WAL (for concurrent reads/writes on file databases)
    - Explicit transaction boundary management
    """
    db_path = get_db_path(db_path_override)
    conn = sqlite3.connect(str(db_path), timeout=settings.DB_BUSY_TIMEOUT_MS / 1000.0)
    conn.row_factory = sqlite3.Row

    try:
        # Enforce foreign key constraints
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute(f"PRAGMA busy_timeout = {settings.DB_BUSY_TIMEOUT_MS};")

        # WAL mode is beneficial for local concurrent read/writes, but not applicable for :memory:
        if str(db_path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")

        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("Database transaction rolled back due to error: %s", type(e).__name__)
        raise
    finally:
        conn.close()
