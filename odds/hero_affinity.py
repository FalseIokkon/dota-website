#!/usr/bin/env python3
"""
hero_affinity.py

Purpose:
Compute each player's affinity for each hero they've played: are they
specifically better or worse on this hero than their own overall average?
That delta-from-baseline is the signal, not a hero's absolute win rate --
the player's overall skill is already captured by the Glicko-2 rating
(player_ratings.py), so this module isolates the *hero-specific* part on
top of that.

Unlike hero_meta.py, this is computed over a player's full history, not
restricted to the current patch -- hero comfort is a longer-run signal than
a single patch's balance, similar to how the player Glicko-2 rating itself
isn't patch-restricted.

Location:
    odds/hero_affinity.py
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass

from .lineups import LINEUPS_CSV

# Shrinkage strength for the affinity delta: shrunk_delta = raw_delta *
# games / (games + K). A player with only a couple of games on a hero gets
# an affinity near 0 (neutral) instead of a noisy +/-50% swing; a player
# with hundreds of games on their signature hero keeps most of their real
# delta.
AFFINITY_SHRINKAGE_K = 15.0


@dataclass
class PlayerHeroStat:
    account_id: object  # int, or "anon_<match>_<slot>" str for hidden profiles
    hero_id: int
    games: int
    win_rate: float
    affinity_delta: float  # shrinkage-discounted delta from this player's own baseline win rate


def compute_hero_affinity(db_path: str) -> dict[tuple, PlayerHeroStat]:
    """
    Compute every (account_id, hero_id) pair's affinity stats from full
    match history.

    Args:
        db_path: Path to dota.db.

    Returns:
        (account_id, hero_id) -> PlayerHeroStat.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        radiant_win_by_match = {
            match_id: bool(radiant_win)
            for match_id, radiant_win in conn.execute("SELECT match_id, radiant_win FROM pro_matches")
        }
    finally:
        conn.close()

    games: dict[tuple, int] = {}
    wins: dict[tuple, int] = {}
    player_games: dict[object, int] = {}
    player_wins: dict[object, int] = {}

    with LINEUPS_CSV.open() as f:
        for row in csv.DictReader(f):
            match_id = int(row["match_id"])
            radiant_win = radiant_win_by_match.get(match_id)
            if radiant_win is None or not row["hero_id"]:
                continue

            account_id = int(row["account_id"]) if row["account_id"].isdigit() else row["account_id"]
            hero_id = int(row["hero_id"])
            is_radiant = row["is_radiant"] == "1"
            won = (is_radiant and radiant_win) or (not is_radiant and not radiant_win)

            key = (account_id, hero_id)
            games[key] = games.get(key, 0) + 1
            player_games[account_id] = player_games.get(account_id, 0) + 1
            if won:
                wins[key] = wins.get(key, 0) + 1
                player_wins[account_id] = player_wins.get(account_id, 0) + 1

    result: dict[tuple, PlayerHeroStat] = {}
    for (account_id, hero_id), n in games.items():
        w = wins.get((account_id, hero_id), 0)
        hero_wr = w / n
        baseline_wr = player_wins.get(account_id, 0) / player_games[account_id]
        raw_delta = hero_wr - baseline_wr
        shrunk_delta = raw_delta * (n / (n + AFFINITY_SHRINKAGE_K))

        result[(account_id, hero_id)] = PlayerHeroStat(
            account_id=account_id,
            hero_id=hero_id,
            games=n,
            win_rate=hero_wr,
            affinity_delta=shrunk_delta,
        )
    return result


def top_heroes(account_id, affinity: dict[tuple, PlayerHeroStat], n: int = 5) -> list[PlayerHeroStat]:
    """
    A player's most-played heroes -- literally "most played heroes for each
    player," sorted by games descending.

    Args:
        account_id: The player's account_id.
        affinity: Output of compute_hero_affinity.
        n: How many heroes to return.

    Returns:
        Up to n PlayerHeroStat, most-played first.
    """
    stats = [s for (acc, _hero_id), s in affinity.items() if acc == account_id]
    stats.sort(key=lambda s: s.games, reverse=True)
    return stats[:n]
