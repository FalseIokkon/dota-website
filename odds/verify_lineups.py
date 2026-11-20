#!/usr/bin/env python3
"""
verify_lineups.py

Purpose:
Sanity-check that a team's "current lineup" (as player_ratings.py would use
it -- the 5 account_ids from its single most recent match) is actually
stable, not a one-off stand-in/exhibition appearance. Checks whether the
same 5 account_ids appear across a team's last N matches; anything less than
unanimous is flagged as a recent roster change worth a manual look before
trusting that team's composite rating.

This doesn't require external data (Liquipedia, OpenDota search) -- it's a
self-contained check against the DB and the lineup cache, so it's cheap to
rerun before every prediction, not just once.

Location:
    odds/verify_lineups.py
"""

import argparse
import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DB_PATH  # noqa: E402
from odds.data import load_matches, latest_team_names  # noqa: E402
from odds.lineups import LINEUPS_CSV  # noqa: E402
from odds.ti2026_teams import TI2026_TEAMS, resolve_team_id  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check recent lineup stability for TI2026 teams.")
    parser.add_argument("--last-n", type=int, default=10, help="How many recent matches to check (default 10).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    matches = load_matches(conn)
    names = latest_team_names(matches)

    lineups_by_match: dict[int, list[dict]] = {}
    with LINEUPS_CSV.open() as f:
        for row in csv.DictReader(f):
            lineups_by_match.setdefault(int(row["match_id"]), []).append(row)

    if not TI2026_TEAMS:
        print("odds/ti2026_teams.py's TI2026_TEAMS is empty -- nothing to verify.")
        return

    for team_name in TI2026_TEAMS:
        lookup = resolve_team_id(team_name, names)
        if lookup.team_id is None:
            print(f"[SKIP] {team_name!r}: could not resolve to a team_id.")
            continue
        team_id = lookup.team_id

        cur = conn.execute("""
            SELECT match_id, radiant_team_id FROM pro_matches
            WHERE radiant_team_id = ? OR dire_team_id = ?
            ORDER BY start_time DESC LIMIT ?
        """, (team_id, team_id, args.last_n))
        recent = cur.fetchall()

        counts: Counter = Counter()
        checked = 0
        for match_id, radiant_team_id in recent:
            rows = lineups_by_match.get(match_id)
            if not rows:
                continue
            side_flag = "1" if radiant_team_id == team_id else "0"
            ids = [r["account_id"] for r in rows if r["is_radiant"] == side_flag]
            if len(ids) == 5:
                counts.update(ids)
                checked += 1

        if checked == 0:
            print(f"[WARN] {team_name!r} (team_id={team_id}): no lineup data in the last {args.last_n} matches.")
            continue

        top5 = counts.most_common(5)
        min_count = min(c for _, c in top5) if len(top5) == 5 else 0
        status = "STABLE" if min_count == checked else "CHANGED"
        print(f"[{status}] {team_name!r} (team_id={team_id}, checked {checked} matches): "
              + ", ".join(f"{acc}x{c}" for acc, c in top5))

    print("\nSTABLE = same 5 players in every recent match checked. "
          "CHANGED = a recent substitution or roster move -- verify manually before trusting that team's composite rating.")


if __name__ == "__main__":
    main()
