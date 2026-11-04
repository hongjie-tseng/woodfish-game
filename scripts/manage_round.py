import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import initialize_database, insert_audit_log, transaction


def main() -> None:
    parser = argparse.ArgumentParser(description="管理電子敲木魚回合")
    parser.add_argument("action", choices=("start", "pause", "resume", "end", "reset"))
    parser.add_argument("--name", default=None, help="新回合名稱（start 時可指定）")
    args = parser.parse_args()
    settings = get_settings()
    initialize_database(settings.database_path)
    with transaction(settings.database_path) as connection:
        state = connection.execute("SELECT round_status FROM game_state WHERE id = 1").fetchone()
        previous_status = state["round_status"]
        allowed = {"pause": {"active"}, "resume": {"paused"}, "end": {"active", "paused"}}
        rejected_error = None
        if args.action in allowed and previous_status not in allowed[args.action]:
            rejected_error = f"Cannot {args.action} while round is {previous_status}"
            insert_audit_log(
                connection, team_id=settings.team_id, action=args.action,
                previous_status=previous_status, new_status=previous_status,
                source="internal", source_ip=None, success=False, error_message=rejected_error,
            )
        if rejected_error is None and args.action == "start":
            connection.execute(
                "UPDATE game_state SET round_status = 'active', round_name = COALESCE(?, round_name), round_taps = 0, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (args.name,),
            )
        elif rejected_error is None and args.action == "pause":
            connection.execute("UPDATE game_state SET round_status = 'paused', updated_at = CURRENT_TIMESTAMP WHERE id = 1")
        elif rejected_error is None and args.action == "resume":
            connection.execute("UPDATE game_state SET round_status = 'active', updated_at = CURRENT_TIMESTAMP WHERE id = 1")
        elif rejected_error is None and args.action == "end":
            connection.execute("UPDATE game_state SET round_status = 'ended', updated_at = CURRENT_TIMESTAMP WHERE id = 1")
        elif rejected_error is None:
            connection.execute("UPDATE game_state SET total_taps = 0, round_taps = 0, updated_at = CURRENT_TIMESTAMP WHERE id = 1")
            connection.execute("DELETE FROM player_totals")
            connection.execute("DELETE FROM processed_taps")
        if rejected_error is None:
            updated = connection.execute("SELECT round_status FROM game_state WHERE id = 1").fetchone()
            insert_audit_log(
                connection, team_id=settings.team_id, action=args.action,
                previous_status=previous_status, new_status=updated["round_status"],
                source="internal", source_ip=None, success=True,
            )
    if rejected_error is not None:
        print(f"Round action failed: {rejected_error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Round action completed: {args.action}")


if __name__ == "__main__":
    main()
