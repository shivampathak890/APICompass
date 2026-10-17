"""Database connection and schema migrations for APICompass v3."""

from app.db.connection import get_db, get_db_path
from app.db.migrations import init_db, CURRENT_SCHEMA_VERSION, MigrationError

__all__ = [
    "get_db",
    "get_db_path",
    "init_db",
    "CURRENT_SCHEMA_VERSION",
    "MigrationError",
]
