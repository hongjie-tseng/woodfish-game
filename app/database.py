import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def connect(database_path: str) -> sqlite3.Connection:
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def initialize_database(
    database_path: str,
    round_name: str = "課堂展示回合",
    round_status: str = "active",
) -> None:
    with connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_taps INTEGER NOT NULL DEFAULT 0,
                round_taps INTEGER NOT NULL DEFAULT 0,
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
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO game_state (id, round_name, round_status)
            VALUES (1, ?, ?)
            """,
            (round_name, round_status),
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
