from dataclasses import dataclass
from pathlib import Path
import hashlib
import secrets
import sqlite3


DEFAULT_DB_PATH = Path("data/linea.db")


@dataclass(frozen=True)
class InitializeDbResult:
    created_new_server_token: bool
    plaintext_server_token: str | None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def initialize_db(db_path: Path = DEFAULT_DB_PATH) -> InitializeDbResult:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS server_auth (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                token TEXT,
                token_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(server_auth)").fetchall()
        }
        if "token" not in columns:
            conn.execute("ALTER TABLE server_auth ADD COLUMN token TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('started', 'success', 'error', 'cancelled')),
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hermes_jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK (status IN (
                    'running', 'completed', 'failed', 'failed_orphaned',
                    'cancel_pending', 'cancelled'
                )),
                task TEXT NOT NULL,
                prompt TEXT NOT NULL,
                profile TEXT NOT NULL,
                profile_home TEXT NOT NULL,
                stdout_path TEXT NOT NULL,
                stderr_path TEXT NOT NULL,
                progress_summary TEXT,
                final_result TEXT,
                delivery_status TEXT NOT NULL DEFAULT 'requested',
                pid INTEGER,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                status_note TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_hermes_jobs_one_active
            ON hermes_jobs ((1))
            WHERE status IN ('running', 'cancel_pending')
            """
        )

        existing = conn.execute("SELECT token FROM server_auth WHERE id = 1").fetchone()
        if existing is not None:
            if existing[0] is not None:
                return InitializeDbResult(False, existing[0])

            token = secrets.token_urlsafe(32)
            conn.execute(
                "UPDATE server_auth SET token = ?, token_hash = ? WHERE id = 1",
                (token, hash_token(token)),
            )
            conn.commit()
            return InitializeDbResult(False, token)

        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO server_auth (id, token, token_hash) VALUES (1, ?, ?)",
            (token, hash_token(token)),
        )
        conn.commit()

    return InitializeDbResult(True, token)
