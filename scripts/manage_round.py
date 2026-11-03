import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import connect, initialize_database


def main() -> None:
    parser = argparse.ArgumentParser(description="管理電子敲木魚回合")
    parser.add_argument("action", choices=("start", "pause", "end", "reset"))
    parser.add_argument("--name", default=None, help="新回合名稱（start 時可指定）")
    args = parser.parse_args()
    settings = get_settings()
    initialize_database(settings.database_path)
    with connect(settings.database_path) as connection:
        if args.action == "start":
            connection.execute(
                "UPDATE game_state SET round_status = 'active', round_name = COALESCE(?, round_name), round_taps = 0, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (args.name,),
            )
        elif args.action == "pause":
            connection.execute("UPDATE game_state SET round_status = 'paused', updated_at = CURRENT_TIMESTAMP WHERE id = 1")
        elif args.action == "end":
            connection.execute("UPDATE game_state SET round_status = 'ended', updated_at = CURRENT_TIMESTAMP WHERE id = 1")
        else:
            connection.execute("UPDATE game_state SET round_taps = 0, updated_at = CURRENT_TIMESTAMP WHERE id = 1")
        connection.commit()
    print(f"Round action completed: {args.action}")


if __name__ == "__main__":
    main()
