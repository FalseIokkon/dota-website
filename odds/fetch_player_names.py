#!/usr/bin/env python3
"""
fetch_player_names.py

Purpose:
Bulk-fetch OpenDota's curated player names (see player_names.py) for every
account_id in the TI2026 rosters' current lineups, and cache them to
data/derived/player_names.json. Run this once, then rerun whenever a
TI2026_LINEUP_OVERRIDES change or a lineup-detection update introduces a new
account_id worth naming.

Location:
    odds/fetch_player_names.py
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DB_PATH  # noqa: E402
from core.opendota_client import OpenDotaClient  # noqa: E402
from odds.player_names import fetch_and_cache_player_names  # noqa: E402
from odds.player_ratings import build_current_player_ratings  # noqa: E402
from odds.ratings import build_current_ratings  # noqa: E402
from odds.ti2026_teams import TI2026_TEAMS, apply_lineup_overrides, resolve_team_id  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch curated player names for the TI2026 rosters.")
    parser.add_argument("--force", action="store_true", help="Re-fetch names already in the cache.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    result = build_current_ratings(str(DB_PATH))
    player_result = build_current_player_ratings(str(DB_PATH))

    account_ids: set[int] = set()
    for team_name in TI2026_TEAMS:
        lookup = resolve_team_id(team_name, result.names)
        if lookup.team_id is None:
            continue
        lineup = player_result.current_lineup_by_team.get(lookup.team_id)
        if not lineup:
            continue
        lineup = apply_lineup_overrides(team_name, lineup)
        account_ids.update(a for a in lineup if isinstance(a, int))

    print(f"Resolving curated names for {len(account_ids)} account_ids...")
    client = OpenDotaClient()
    cache = fetch_and_cache_player_names(sorted(account_ids), client, force=args.force)

    print(f"\nCache now has {len(cache)} entries.")
    for account_id in sorted(account_ids):
        print(f"  {account_id}: {cache.get(account_id, '(unresolved)')}")


if __name__ == "__main__":
    main()
