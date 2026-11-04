"""In-memory hot path for taps, written to SQLite in batches.

Taps only touch memory; a background task calls flush() every FLUSH_INTERVAL_SECONDS and writes the
batch in one transaction. A crash can lose the last unflushed batch, which is acceptable for the game.
After every flush the snapshot is reloaded from SQLite, so changes made by scripts/manage_round.py
still show up within one interval.
"""
import threading
import time
from collections import Counter
from typing import Callable, TypeVar

from .database import transaction

FLUSH_INTERVAL_SECONDS = 0.5
# Clients retry a tap for at most about 30 s (3 attempts x 10 s timeout), so duplicates are only
# tracked for this long, both in memory and in processed_taps.
DUPLICATE_WINDOW_SECONDS = 120
PRUNE_INTERVAL_SECONDS = 10

T = TypeVar("T")


class RoundNotActive(Exception):
    pass


class TapStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self.lock = threading.Lock()
        # Serializes flushes with admin actions so an action always sees every accepted tap.
        self.flush_lock = threading.RLock()
        self.recent: dict[str, float] = {}
        self.pending: list[tuple[str, str]] = []
        self.pending_players: Counter[str] = Counter()
        self.pending_requests = 0
        self.flushing: list[tuple[str, str]] = []
        self.flushing_players: Counter[str] = Counter()
        self.flushing_requests = 0
        self.last_prune = 0.0
        with transaction(database_path) as connection:
            self.state, self.players = self._read_snapshot(connection)

    @staticmethod
    def _read_snapshot(connection) -> tuple[dict, dict[str, int]]:
        state = dict(connection.execute("SELECT * FROM game_state WHERE id = 1").fetchone())
        players = {
            row["player_id"]: row["tap_count"]
            for row in connection.execute("SELECT player_id, tap_count FROM player_totals")
        }
        return state, players

    def _view(self, player_id: str | None = None) -> dict:
        unflushed = len(self.flushing) + len(self.pending)
        view = {
            "team_taps": self.state["total_taps"] + unflushed,
            "round_taps": self.state["round_taps"] + unflushed,
            "round_name": self.state["round_name"],
            "round_status": self.state["round_status"],
            "tap_requests_total": self.state["tap_requests_total"] + self.flushing_requests + self.pending_requests,
            "tap_requests_reset_base": self.state["tap_requests_reset_base"],
        }
        if player_id is not None:
            view["personal_taps"] = (
                self.players.get(player_id, 0)
                + self.flushing_players[player_id]
                + self.pending_players[player_id]
            )
        return view

    def snapshot(self, player_id: str | None = None) -> dict:
        with self.lock:
            return self._view(player_id)

    def count_request(self) -> None:
        with self.lock:
            self.pending_requests += 1

    def tap(self, tap_id: str, player_id: str) -> tuple[bool, dict]:
        """Returns (duplicate, state); raises RoundNotActive when the round is not running."""
        now = time.monotonic()
        with self.lock:
            while self.recent:
                oldest = next(iter(self.recent))
                if now - self.recent[oldest] < DUPLICATE_WINDOW_SECONDS:
                    break
                del self.recent[oldest]
            if tap_id in self.recent:
                return True, self._view(player_id)
            if self.state["round_status"] != "active":
                raise RoundNotActive
            self.recent[tap_id] = now
            self.pending.append((tap_id, player_id))
            self.pending_players[player_id] += 1
            return False, self._view(player_id)

    def flush(self) -> None:
        with self.flush_lock:
            with self.lock:
                batch, self.pending = self.pending, []
                batch_players, self.pending_players = self.pending_players, Counter()
                requests, self.pending_requests = self.pending_requests, 0
                self.flushing, self.flushing_players, self.flushing_requests = batch, batch_players, requests
            try:
                with transaction(self.database_path) as connection:
                    inserted: Counter[str] = Counter()
                    for tap_id, player_id in batch:
                        # The database also rejects retries that arrive after a restart cleared memory.
                        if connection.execute(
                            "INSERT OR IGNORE INTO processed_taps (tap_id, player_id) VALUES (?, ?)",
                            (tap_id, player_id),
                        ).rowcount:
                            inserted[player_id] += 1
                    connection.executemany(
                        """
                        INSERT INTO player_totals (player_id, tap_count) VALUES (?, ?)
                        ON CONFLICT(player_id) DO UPDATE SET
                            tap_count = tap_count + excluded.tap_count,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        inserted.items(),
                    )
                    taps = sum(inserted.values())
                    if taps or requests:
                        connection.execute(
                            """
                            UPDATE game_state
                            SET total_taps = total_taps + ?, round_taps = round_taps + ?,
                                tap_requests_total = tap_requests_total + ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                            """,
                            (taps, taps, requests),
                        )
                    now = time.monotonic()
                    if now - self.last_prune >= PRUNE_INTERVAL_SECONDS:
                        connection.execute(
                            "DELETE FROM processed_taps WHERE created_at < datetime('now', ?)",
                            (f"-{DUPLICATE_WINDOW_SECONDS} seconds",),
                        )
                        self.last_prune = now
                    state, players = self._read_snapshot(connection)
            except Exception:
                with self.lock:
                    self.pending = batch + self.pending
                    self.pending_players.update(batch_players)
                    self.pending_requests += requests
                    self.flushing, self.flushing_players, self.flushing_requests = [], Counter(), 0
                raise
            with self.lock:
                self.state, self.players = state, players
                self.flushing, self.flushing_players, self.flushing_requests = [], Counter(), 0

    def admin(self, action: Callable[[], T], *, clear_duplicates: bool = False) -> T:
        """Flush, run an admin transaction, then reload so memory matches the database again."""
        with self.flush_lock:
            self.flush()
            try:
                return action()
            finally:
                with transaction(self.database_path) as connection:
                    state, players = self._read_snapshot(connection)
                with self.lock:
                    self.state, self.players = state, players
                    if clear_duplicates:
                        self.recent.clear()
