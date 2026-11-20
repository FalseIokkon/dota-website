#!/usr/bin/env python3
"""
team_tendencies.py

Purpose:
Team-level draft tendencies: which heroes a given team_id picks most often
and which it bans most often, across its full match history. Complements
odds/hero_affinity.py (per-player) and odds/hero_meta.py (per-hero,
patch-wide) with the one grouping neither of those covers.

data/derived/picks_bans.csv has no team_id column (match_id, hero_id,
is_pick, is_radiant, order) -- this joins it against odds.data.load_matches'
match_id -> (team_a, team_b) map, using is_radiant to pick which side of
that match made each row (team_a is the radiant team_id, same convention
odds/lineups.py's MatchLineup already documents).

Deliberately not patch-restricted (unlike hero_meta.py) -- a single team's
draft history is far sparser than the whole scene's, so patch-filtering
would leave most teams with almost no data.

Location:
    webapp/team_tendencies.py
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from odds.data import load_matches

PICKS_BANS_CSV = Path(__file__).resolve().parents[1] / "data" / "derived" / "picks_bans.csv"


@dataclass
class HeroCount:
    hero_id: int
    count: int
    rate: float  # count / that team's total picks (or bans)


@dataclass
class TeamHeroTendency:
    team_id: int
    total_picks: int
    total_bans: int
    top_picks: list[HeroCount] = field(default_factory=list)
    top_bans: list[HeroCount] = field(default_factory=list)


def compute_team_pick_ban_tendencies(db_path: str, top_n: int = 10) -> dict[int, TeamHeroTendency]:
    """
    Compute each team_id's most-picked and most-banned heroes across its
    full match history.

    Args:
        db_path: Path to dota.db (only used to build the match_id -> team
            map -- the counts themselves come from picks_bans.csv).
        top_n: How many heroes to keep per list.

    Returns:
        team_id -> TeamHeroTendency. Teams with no rows in picks_bans.csv
        simply don't appear -- callers should treat a missing team_id as
        "no draft history cached yet."
    """
    if not PICKS_BANS_CSV.exists():
        return {}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        matches = load_matches(conn)
    finally:
        conn.close()

    team_by_match: dict[int, tuple[int, int]] = {m.match_id: (m.team_a, m.team_b) for m in matches}

    picks: dict[int, dict[int, int]] = {}  # team_id -> hero_id -> count
    bans: dict[int, dict[int, int]] = {}

    with PICKS_BANS_CSV.open() as f:
        for row in csv.DictReader(f):
            if not row["hero_id"]:
                continue
            match_id = int(row["match_id"])
            sides = team_by_match.get(match_id)
            if sides is None:
                continue
            team_a, team_b = sides
            team_id = team_a if row["is_radiant"] == "1" else team_b
            hero_id = int(row["hero_id"])

            bucket = picks if row["is_pick"] == "1" else bans
            team_counts = bucket.setdefault(team_id, {})
            team_counts[hero_id] = team_counts.get(hero_id, 0) + 1

    all_team_ids = set(picks) | set(bans)
    result: dict[int, TeamHeroTendency] = {}
    for team_id in all_team_ids:
        team_picks = picks.get(team_id, {})
        team_bans = bans.get(team_id, {})
        total_picks = sum(team_picks.values())
        total_bans = sum(team_bans.values())

        top_picks = sorted(
            (HeroCount(hero_id, n, n / total_picks) for hero_id, n in team_picks.items()),
            key=lambda h: h.count, reverse=True,
        )[:top_n]
        top_bans = sorted(
            (HeroCount(hero_id, n, n / total_bans) for hero_id, n in team_bans.items()),
            key=lambda h: h.count, reverse=True,
        )[:top_n]

        result[team_id] = TeamHeroTendency(
            team_id=team_id,
            total_picks=total_picks,
            total_bans=total_bans,
            top_picks=top_picks,
            top_bans=top_bans,
        )
    return result
