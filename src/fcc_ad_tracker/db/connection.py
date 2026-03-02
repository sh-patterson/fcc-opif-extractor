from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_schema_sql() -> str:
    return _SCHEMA_PATH.read_text()


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database and apply the schema."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(get_schema_sql())
    # Migrations for older DBs created before additional columns/indexes existed.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
    if "file_type" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN file_type TEXT DEFAULT 'unknown'")
    if "extraction_status" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN extraction_status TEXT DEFAULT 'pending'")
    if "create_ts" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN create_ts TEXT")
    if "last_update_ts" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN last_update_ts TEXT")
    if "history_status" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN history_status TEXT")

    contract_cols = {r[1] for r in conn.execute("PRAGMA table_info(contracts)")}
    if "candidate_id" not in contract_cols:
        conn.execute("ALTER TABLE contracts ADD COLUMN candidate_id INTEGER")
    if "office_sought" not in contract_cols:
        conn.execute("ALTER TABLE contracts ADD COLUMN office_sought TEXT")
    if "extraction_method" not in contract_cols:
        conn.execute("ALTER TABLE contracts ADD COLUMN extraction_method TEXT")

    line_item_cols = {r[1] for r in conn.execute("PRAGMA table_info(line_items)")}
    if "extraction_method" not in line_item_cols:
        conn.execute("ALTER TABLE line_items ADD COLUMN extraction_method TEXT")

    # Backfill extraction_status for existing files.
    conn.execute(
        """
        UPDATE files
        SET extraction_status = CASE
            WHEN file_id IN (SELECT DISTINCT file_id FROM extractions) THEN 'done'
            WHEN downloaded_at IS NOT NULL THEN 'pending'
            ELSE extraction_status
        END
        WHERE extraction_status IS NULL OR extraction_status = ''
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_files_extraction_status ON files(extraction_status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_contracts_candidate_id ON contracts(candidate_id)"
    )
    conn.commit()
