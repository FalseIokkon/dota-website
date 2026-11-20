#!/usr/bin/env python3
"""
hero_meta.py

Purpose:
Compute each hero's current-patch win rate and pick rate from our own
scraped pro matches, instead of pulling this from an external site. Patch
is intentionally not blended across eras -- see the shrinkage note below --
so a hero's number only ever reflects the patch actually being played now.

`matches.patch` is a small INTEGER column and is cheap to read on its own
(confirmed: 2000 rows in ~0.006s) as long as `payload_json` isn't also
selected -- SQLite doesn't touch payload_json's overflow pages unless that
column is part of the query. This module never touches payload_json.

Location:
    odds/hero_meta.py
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass

from .lineups import LINEUPS_CSV

PICKS_BANS_CSV = LINEUPS_CSV.parent / "picks_bans.csv"

# Bayesian shrinkage strength for hero win rate: shrunk_wr = (wins + K*0.5) /
# (games + K). A hero with few current-patch games gets pulled toward a
# neutral 50% instead of producing a noisy extreme estimate. This is the
# mechanism that replaces cross-patch blending entirely -- nothing from an
# older patch ever gets mixed in, low-sample heroes are just treated as
# "unknown, assume average" until the current patch has enough games on them.
META_SHRINKAGE_K = 30.0


@dataclass
class HeroMeta:
    hero_id: int
    games: int
    win_rate_raw: float
    win_rate_shrunk: float
    pick_rate: float  # fraction of current-patch matches featuring this hero
    ban_count: int = 0
    ban_rate: float = 0.0  # fraction of current-patch matches this hero was banned in
    presence_rate: float = 0.0  # pick_rate + ban_rate: how much of the draft it occupies


def _current_patch_match_ids(db_path: str) -> tuple[int, set[int]]:
    """
    Returns (current_patch, set of match_ids on that patch). Only reads
    (match_id, patch) -- never payload_json.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT match_id, patch FROM matches WHERE patch IS NOT NULL").fetchall()
    finally:
        conn.close()

    if not rows:
        return 0, set()

    current_patch = max(patch for _, patch in rows)
    match_ids = {match_id for match_id, patch in rows if patch == current_patch}
    return current_patch, match_ids


def current_patch(db_path: str) -> int:
    """The highest patch value seen in `matches` -- used for display only."""
    patch, _ = _current_patch_match_ids(db_path)
    return patch


def compute_hero_meta(db_path: str) -> dict[int, HeroMeta]:
    """
    Compute current-patch HeroMeta for every hero seen this patch.

    Args:
        db_path: Path to dota.db.

    Returns:
        hero_id -> HeroMeta. Heroes with zero games this patch simply don't
        appear -- callers should treat a missing hero_id as "no data yet,
        assume neutral" (see hero_adjustment.py).
    """
    current_patch, patch_match_ids = _current_patch_match_ids(db_path)
    if not patch_match_ids:
        return {}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        radiant_win_by_match = {
            match_id: bool(radiant_win)
            for match_id, radiant_win in conn.execute("SELECT match_id, radiant_win FROM pro_matches")
        }
    finally:
        conn.close()

    games: dict[int, int] = {}
    wins: dict[int, int] = {}
    total_matches = 0
    seen_matches: set[int] = set()

    with LINEUPS_CSV.open() as f:
        for row in csv.DictReader(f):
            match_id = int(row["match_id"])
            if match_id not in patch_match_ids:
                continue
            radiant_win = radiant_win_by_match.get(match_id)
            if radiant_win is None or not row["hero_id"]:
                continue

            seen_matches.add(match_id)
            hero_id = int(row["hero_id"])
            is_radiant = row["is_radiant"] == "1"
            won = (is_radiant and radiant_win) or (not is_radiant and not radiant_win)

            games[hero_id] = games.get(hero_id, 0) + 1
            if won:
                wins[hero_id] = wins.get(hero_id, 0) + 1

    total_matches = len(seen_matches)
    if total_matches == 0:
        return {}

    bans: dict[int, int] = {}
    if PICKS_BANS_CSV.exists():
        with PICKS_BANS_CSV.open() as f:
            for row in csv.DictReader(f):
                match_id = int(row["match_id"])
                if match_id not in patch_match_ids or not row["hero_id"]:
                    continue
                if row["is_pick"] == "0":
                    hero_id = int(row["hero_id"])
                    bans[hero_id] = bans.get(hero_id, 0) + 1

    result: dict[int, HeroMeta] = {}
    all_hero_ids = set(games) | set(bans)
    for hero_id in all_hero_ids:
        n = games.get(hero_id, 0)
        w = wins.get(hero_id, 0)
        ban_count = bans.get(hero_id, 0)
        pick_rate = n / total_matches
        ban_rate = ban_count / total_matches
        result[hero_id] = HeroMeta(
            hero_id=hero_id,
            games=n,
            win_rate_raw=(w / n) if n > 0 else 0.0,
            win_rate_shrunk=(w + META_SHRINKAGE_K * 0.5) / (n + META_SHRINKAGE_K),
            pick_rate=pick_rate,
            ban_count=ban_count,
            ban_rate=ban_rate,
            presence_rate=pick_rate + ban_rate,
        )
    return result
