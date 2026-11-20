#!/usr/bin/env python3
"""
lineups.py

Purpose:
Load the cached per-match lineups (data/derived/lineups.csv, built by
build_lineups.py) and attach them to the MatchRow list data.py already
produces from pro_matches, so each match carries both its outcome and the
10 account_ids who played it. This is the input player_ratings.py consumes.

Location:
    odds/lineups.py
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .data import MatchRow

LINEUPS_CSV = Path(__file__).resolve().parents[1] / "data" / "derived" / "lineups.csv"

# account_id is normally a Steam32 int, but build_lineups.py substitutes a
# per-match sentinel string ("anon_<match_id>_<slot>") for players with a
# hidden profile, so it's typed loosely (int | str) rather than strictly int.


@dataclass
class MatchLineup:
    match_id: int
    start_time: int
    period: int
    team_a: int  # radiant team_id, matches MatchRow.team_a
    team_b: int  # dire team_id, matches MatchRow.team_b
    score_a: float
    radiant_ids: list
    dire_ids: list


@dataclass
class LineupData:
    lineups: list[MatchLineup]
    player_names: dict  # account_id -> most-recently-seen personaname
    current_lineup_by_team: dict  # team_id -> most-recently-fielded 5 account_ids


def _parse_account_id(raw: str):
    return int(raw) if raw.isdigit() else raw


def load_lineups(matches: list[MatchRow], csv_path: Path = LINEUPS_CSV) -> LineupData:
    """
    Join the lineup cache onto a chronologically-sorted MatchRow list.

    Args:
        matches: Output of data.load_matches (sorted by start_time).
        csv_path: Path to the CSV built by build_lineups.py.

    Returns:
        LineupData. Matches with no cached lineup yet, or a malformed one
        (not exactly 5-a-side), are silently skipped -- rerun
        build_lineups.py to pick up newly-scraped matches.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"No lineup cache at {csv_path}. Run: python3 odds/build_lineups.py")

    rows_by_match: dict[int, list[tuple]] = {}
    with csv_path.open() as f:
        for row in csv.DictReader(f):
            match_id = int(row["match_id"])
            account_id = _parse_account_id(row["account_id"])
            rows_by_match.setdefault(match_id, []).append(
                (account_id, row["personaname"], row["is_radiant"] == "1")
            )

    lineups: list[MatchLineup] = []
    player_names: dict = {}
    current_lineup_by_team: dict = {}

    for m in matches:
        rows = rows_by_match.get(m.match_id)
        if not rows:
            continue

        radiant_ids = [account_id for account_id, _, is_radiant in rows if is_radiant]
        dire_ids = [account_id for account_id, _, is_radiant in rows if not is_radiant]
        if len(radiant_ids) != 5 or len(dire_ids) != 5:
            continue

        for account_id, name, _ in rows:
            if name:
                player_names[account_id] = name

        # Matches are processed in chronological order, so the last write
        # for a team_id is always its most-recently-fielded lineup.
        current_lineup_by_team[m.team_a] = radiant_ids
        current_lineup_by_team[m.team_b] = dire_ids

        lineups.append(MatchLineup(
            match_id=m.match_id,
            start_time=m.start_time,
            period=m.period,
            team_a=m.team_a,
            team_b=m.team_b,
            score_a=m.score_a,
            radiant_ids=radiant_ids,
            dire_ids=dire_ids,
        ))

    return LineupData(lineups=lineups, player_names=player_names, current_lineup_by_team=current_lineup_by_team)
