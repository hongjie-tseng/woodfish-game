import gc
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def make_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TEAM_ID", "TEST")
    monkeypatch.setenv("TEAM_NAME", "測試隊")
    monkeypatch.setenv("ADMIN_PROXY_IP", "testclient")
    import app.config
    import app.main
    app.config.get_settings.cache_clear()
    app.main.settings = app.config.get_settings()
    app.main.initialize_database(app.main.settings.database_path)
    return TestClient(app.main.app), app.main


def test_tap_is_idempotent(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    first = client.post("/api/tap", json={"tap_id": "tap-unique-1", "player_id": "player-unique-1"})
    duplicate = client.post("/api/tap", json={"tap_id": "tap-unique-1", "player_id": "player-unique-1"})
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json()["duplicate"] is False
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["team_taps"] == 1


def test_stats_and_health(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    assert client.get("/health").json()["status"] == "ok"
    client.post("/api/tap", json={"tap_id": "tap-unique-2", "player_id": "player-unique-2"})
    stats = client.get("/api/stats?player_id=player-unique-2")
    assert stats.json()["personal_taps"] == 1
    assert stats.json()["team_taps"] == 1


def test_metrics_counts_success_duplicate_and_failed_tap_requests(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    assert client.post(
        "/api/tap", json={"tap_id": "metrics-tap-1", "player_id": "metrics-player-1"}
    ).status_code == 200
    assert client.post(
        "/api/tap", json={"tap_id": "metrics-tap-1", "player_id": "metrics-player-1"}
    ).status_code == 200
    assert client.post("/api/tap", json={"invalid": True}).status_code == 422
    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["tap_requests_total"] == 3
    assert metrics.headers["cache-control"] == "no-store, max-age=0"


def test_media_woodfish_sound_is_served(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    sound = client.get("/static/assets/woodfish-hit.wav")
    assert sound.status_code == 200
    assert sound.headers["content-type"].startswith("audio/wav")
    assert len(sound.content) > 1000


def test_version_endpoint_and_index_cache_headers(tmp_path, monkeypatch):
    client, main = make_client(tmp_path, monkeypatch)
    version = client.get("/api/version")
    index = client.get("/")
    assert version.status_code == 200
    assert version.json()["version"] != ""
    assert "commit" in version.json()
    assert index.headers["cache-control"] == "no-store, max-age=0"
    assert "__ASSET_VERSION__" not in index.text
    assert 'class="connection connection--pending">連線中</span>' in index.text


def test_paused_round_rejects_taps(tmp_path, monkeypatch):
    client, main = make_client(tmp_path, monkeypatch)
    with main.connect(main.settings.database_path) as connection:
        connection.execute("UPDATE game_state SET round_status = 'paused' WHERE id = 1")
        connection.commit()
    response = client.post("/api/tap", json={"tap_id": "tap-unique-3", "player_id": "player-unique-3"})
    assert response.status_code == 409


def test_admin_status_and_round_actions_are_available_to_proxy(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    status = client.get("/api/admin/status")
    assert status.status_code == 200
    assert status.json()["team_name"] == "測試隊"
    response = client.post("/api/admin/round/pause", json={})
    assert response.status_code == 200
    assert response.json()["round_status"] == "paused"
    response = client.post("/api/admin/round/resume", json={})
    assert response.status_code == 200
    assert response.json()["round_status"] == "active"
    logs = client.get("/api/admin/audit-logs?limit=10")
    assert logs.status_code == 200
    assert [(item["action"], item["previous_status"], item["new_status"]) for item in logs.json()[:2]] == [
        ("resume", "paused", "active"),
        ("pause", "active", "paused"),
    ]


def test_rejected_admin_action_is_audited(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    assert client.post("/api/admin/round/pause", json={}).status_code == 200
    response = client.post("/api/admin/round/pause", json={})
    assert response.status_code == 409
    log = client.get("/api/admin/audit-logs?limit=1").json()[0]
    assert log["action"] == "pause"
    assert log["success"] is False
    assert log["previous_status"] == "paused"
    assert "Cannot pause" in log["error_message"]


def test_admin_api_rejects_non_monitor_source(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    monkeypatch.setenv("ADMIN_PROXY_IP", "192.168.26.131")
    import app.config
    import app.main
    app.config.get_settings.cache_clear()
    app.main.settings = app.config.get_settings()
    assert client.get("/api/admin/status").status_code == 403


def test_admin_reset_clears_team_and_all_player_scores(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    for tap_id, player_id in (("reset-tap-a", "reset-player-a"), ("reset-tap-b", "reset-player-b")):
        assert client.post(
            "/api/tap", json={"tap_id": tap_id, "player_id": player_id}
        ).status_code == 200

    before = client.get("/api/admin/status").json()
    assert before["team_taps"] == 2
    response = client.post("/api/admin/round/reset", json={})
    assert response.status_code == 200
    assert response.json()["team_taps"] == 0
    assert response.json()["round_taps"] == 0
    assert client.get("/api/stats?player_id=reset-player-a").json()["personal_taps"] == 0
    assert client.get("/api/stats?player_id=reset-player-b").json()["personal_taps"] == 0
    assert client.get("/api/metrics").json()["tap_requests_total"] == 2
    logs = client.get("/api/admin/audit-logs?limit=1").json()
    assert logs[0]["action"] == "reset"
    assert logs[0]["success"] is True


def test_database_migration_preserves_existing_state_and_metrics(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy.db"
    import sqlite3

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_taps INTEGER NOT NULL DEFAULT 0,
                round_taps INTEGER NOT NULL DEFAULT 0,
                tap_requests_total INTEGER NOT NULL DEFAULT 0,
                round_name TEXT NOT NULL DEFAULT '課堂展示回合',
                round_status TEXT NOT NULL DEFAULT 'active',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO game_state (id, total_taps, round_taps, tap_requests_total, round_status)
            VALUES (1, 12, 4, 99, 'paused');
            """
        )
    client, _ = make_client(tmp_path, monkeypatch)
    with client:
        pass
    import app.main

    app.main.initialize_database(str(database_path))
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT total_taps, round_taps, round_status, tap_requests_total FROM game_state WHERE id = 1"
        ).fetchone()
        assert row == (12, 4, "paused", 99)
        assert connection.execute("SELECT COUNT(*) FROM admin_audit_logs").fetchone()[0] == 0


def test_startup_preserves_status_and_records_event(tmp_path, monkeypatch):
    client, main = make_client(tmp_path, monkeypatch)
    with main.transaction(main.settings.database_path) as connection:
        connection.execute("UPDATE game_state SET round_status = 'paused' WHERE id = 1")
    with client:
        pass
    with main.connect(main.settings.database_path) as connection:
        row = connection.execute(
            "SELECT action, previous_status, new_status, source, success, error_message "
            "FROM admin_audit_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert tuple(row) == (
        "startup",
        "paused",
        "paused",
        "system_startup",
        1,
        "Persisted round status; no startup override applied",
    )


def test_connect_context_closes_connection(tmp_path, monkeypatch):
    _, main = make_client(tmp_path, monkeypatch)
    with main.connect(main.settings.database_path) as connection:
        connection.execute("SELECT 1").fetchone()
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_requests_do_not_leak_database_connections(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    client.get("/health")
    gc.disable()
    try:
        before = len(os.listdir("/proc/self/fd")) if os.path.isdir("/proc/self/fd") else None
        for _ in range(50):
            assert client.get("/health").status_code == 200
        after = len(os.listdir("/proc/self/fd")) if before is not None else None
    finally:
        gc.enable()
    if before is not None:
        assert after - before < 10
