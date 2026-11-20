#!/usr/bin/env python3
"""
data.py

Purpose:
Load pro match rows out of the shared database and normalize them into the
flat (period, team_a, team_b, score_a) shape the rating pipeline consumes.

Location:
    odds/data.py
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# Rating periods are Unix-epoch-aligned weekly bins (not calendar/ISO weeks).
# This keeps binning a pure function of start_time with no timezone handling;
# the only effect is which side of a week boundary a match falls on.
PERIOD_SECONDS = 7 * 24 * 60 * 60


@dataclass
class MatchRow:
    match_id: int
    start_time: int
    period: int
    team_a: int
    name_a: str
    team_b: int
    name_b: str
    score_a: float  # 1.0 if team_a won, 0.0 otherwise
    league_name: str


def load_matches(conn: sqlite3.Connection) -> list[MatchRow]:
    """
    Load all usable pro matches, sorted chronologically.

    Rows missing a team id on either side (unknown/amateur opponents,
    ~5% of pro_matches) are dropped since they can't be rated.

    Args:
        conn: Open SQLite connection to dota.db.

    Returns:
        MatchRow list sorted by start_time ascending.
    """
    rows = conn.execute("""
        SELECT match_id, start_time, radiant_team_id, radiant_name,
               dire_team_id, dire_name, radiant_win, league_name
        FROM pro_matches
        WHERE radiant_team_id IS NOT NULL AND radiant_team_id != 0
          AND dire_team_id IS NOT NULL AND dire_team_id != 0
          AND radiant_win IS NOT NULL
        ORDER BY start_time ASC, match_id ASC
    """).fetchall()

    matches = []
    for r in rows:
        start_time = r["start_time"]
        matches.append(MatchRow(
            match_id=r["match_id"],
            start_time=start_time,
            period=start_time // PERIOD_SECONDS,
            team_a=r["radiant_team_id"],
            name_a=r["radiant_name"] or f"team_{r['radiant_team_id']}",
            team_b=r["dire_team_id"],
            name_b=r["dire_name"] or f"team_{r['dire_team_id']}",
            score_a=1.0 if r["radiant_win"] else 0.0,
            league_name=r["league_name"] or "",
        ))
    return matches


def latest_team_names(matches: list[MatchRow]) -> dict[int, str]:
    """
    Build a team_id -> most-recently-seen display name map.

    Team orgs rebrand fairly often; team_id is the stable rating key, but we
    still want a readable current name for display and for name-based lookup.

    Args:
        matches: Chronologically sorted MatchRow list (as returned by
            load_matches).

    Returns:
        Mapping of team_id to its name as of the latest match seen.
    """
    names: dict[int, str] = {}
    for m in matches:
        names[m.team_a] = m.name_a
        names[m.team_b] = m.name_b
    return names
