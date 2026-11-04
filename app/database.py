import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class ClosingConnection(sqlite3.Connection):
    """sqlite3's own context manager only commits or rolls back; also close so file descriptors are released."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(database_path: str) -> sqlite3.Connection:
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=30.0, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def initialize_database(
    database_path: str,
    round_name: str = "課堂展示回合",
    round_status: str = "active",
) -> bool:
    state_created = False
    with connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_taps INTEGER NOT NULL DEFAULT 0,
                round_taps INTEGER NOT NULL DEFAULT 0,
                tap_requests_total INTEGER NOT NULL DEFAULT 0,
                round_name TEXT NOT NULL DEFAULT '課堂展示回合',
                round_status TEXT NOT NULL DEFAULT 'active',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS player_totals (
                player_id TEXT PRIMARY KEY,
                tap_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS processed_taps (
                tap_id TEXT PRIMARY KEY,
                player_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_processed_taps_created_at
                ON processed_taps(created_at);
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                team_id TEXT NOT NULL,
                action TEXT NOT NULL,
                previous_status TEXT NOT NULL,
                new_status TEXT NOT NULL,
                source TEXT NOT NULL,
                source_ip TEXT,
                success INTEGER NOT NULL CHECK (success IN (0, 1)),
                error_message TEXT,
                git_commit TEXT,
                state_initialized INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_timestamp
                ON admin_audit_logs(timestamp DESC);
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(game_state)").fetchall()
        }
        existing_state = connection.execute(
            "SELECT 1 FROM game_state WHERE id = 1"
        ).fetchone()
        if "tap_requests_total" not in columns:
            connection.execute(
                "ALTER TABLE game_state ADD COLUMN tap_requests_total INTEGER NOT NULL DEFAULT 0"
            )
        audit_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(admin_audit_logs)").fetchall()
        }
        for column, definition in (
            ("git_commit", "TEXT"),
            ("state_initialized", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in audit_columns:
                connection.execute(
                    f"ALTER TABLE admin_audit_logs ADD COLUMN {column} {definition}"
                )
        connection.execute(
            """
            INSERT OR IGNORE INTO game_state (id, round_name, round_status)
            VALUES (1, ?, ?)
            """,
            (round_name, round_status),
        )
        state_created = existing_state is None
    return state_created


def insert_audit_log(
    connection: sqlite3.Connection,
    *,
    team_id: str,
    action: str,
    previous_status: str,
    new_status: str,
    source: str,
    source_ip: str | None,
    success: bool,
    error_message: str | None = None,
    git_commit: str | None = None,
    state_initialized: bool = False,
) -> None:
    connection.execute(
        """
        INSERT INTO admin_audit_logs (
            team_id, action, previous_status, new_status, source, source_ip,
            success, error_message, git_commit, state_initialized
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            team_id,
            action,
            previous_status,
            new_status,
            source,
            source_ip,
            int(success),
            error_message,
            git_commit,
            int(state_initialized),
        ),
    )
    connection.execute(
        """
        DELETE FROM admin_audit_logs
        WHERE id NOT IN (
            SELECT id FROM admin_audit_logs ORDER BY timestamp DESC, id DESC LIMIT 10000
        )
        """
    )


@contextmanager
def transaction(database_path: str) -> Iterator[sqlite3.Connection]:
    connection = connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
