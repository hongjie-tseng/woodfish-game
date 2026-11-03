from pathlib import Path

from fastapi.testclient import TestClient


def make_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TEAM_ID", "TEST")
    monkeypatch.setenv("TEAM_NAME", "測試隊")
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


def test_version_endpoint_and_index_cache_headers(tmp_path, monkeypatch):
    client, main = make_client(tmp_path, monkeypatch)
    version = client.get("/api/version")
    index = client.get("/")
    assert version.status_code == 200
    assert version.json()["version"] != ""
    assert "commit" in version.json()
    assert index.headers["cache-control"] == "no-store, max-age=0"
    assert "__ASSET_VERSION__" not in index.text


def test_paused_round_rejects_taps(tmp_path, monkeypatch):
    client, main = make_client(tmp_path, monkeypatch)
    with main.connect(main.settings.database_path) as connection:
        connection.execute("UPDATE game_state SET round_status = 'paused' WHERE id = 1")
        connection.commit()
    response = client.post("/api/tap", json={"tap_id": "tap-unique-3", "player_id": "player-unique-3"})
    assert response.status_code == 409
