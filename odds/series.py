#!/usr/bin/env python3
"""
series.py

Purpose:
Convert a single-game win probability into best-of-N series outcomes.

Why this exists:
`pro_matches` stores individual games, not series results -- confirmed via
`series_id`, which groups 2-6 separate match_ids into one Bo3/Bo5 (2-3 for
almost all of them; higher counts are rare rescheduled/restarted series).
The whole rating pipeline (data.py, ratings.py, player_ratings.py) treats
every game as one independent observation, so glicko2.expected_score's
output is a per-GAME probability. Bookmaker "Match Winner" markets are
per-SERIES (Bo3 at TI2026's group stage and most playoff rounds), so
comparing the two directly -- which every EV calculation in this project
did before this module existed -- understates a favorite's true series win
probability and overstates an underdog's, more so the more lopsided the
individual-game probability already is. Assumes each game in the series is
independent and identically distributed at the given single-game
probability (no momentum/fatigue/map-side modeling) -- the standard
simplifying assumption for this conversion.

Location:
    odds/series.py
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb


def series_win_probability(p_game: float, best_of: int = 3) -> float:
    """
    P(side A wins a best-of-`best_of` series), given they win each
    independent game with probability p_game. best_of must be odd.
    """
    wins_needed = best_of // 2 + 1
    total = 0.0
    # P(A wins in exactly `wins_needed + losses` games) summed over losses
    for losses in range(wins_needed):
        games_played = wins_needed + losses
        # A wins the last game, and wins (wins_needed - 1) of the prior
        # (games_played - 1) games.
        ways = comb(games_played - 1, losses)
        total += ways * (p_game ** wins_needed) * ((1 - p_game) ** losses)
    return total


@dataclass
class ScoreOutcome:
    wins_a: int
    wins_b: int
    probability: float


def series_score_distribution(p_game: float, best_of: int = 3) -> list[ScoreOutcome]:
    """
    Probability of each exact scoreline (e.g. 2-0, 2-1, 1-2, 0-2 for a
    Bo3), given each independent game is won by side A with probability
    p_game. Returns one ScoreOutcome per possible final score, sorted
    A-wins scorelines first.
    """
    wins_needed = best_of // 2 + 1
    outcomes = []
    for losses in range(wins_needed):
        games_played = wins_needed + losses
        ways = comb(games_played - 1, losses)
        prob = ways * (p_game ** wins_needed) * ((1 - p_game) ** losses)
        outcomes.append(ScoreOutcome(wins_a=wins_needed, wins_b=losses, probability=prob))
    for wins in range(wins_needed):
        games_played = wins_needed + wins
        ways = comb(games_played - 1, wins)
        prob = ways * ((1 - p_game) ** wins_needed) * (p_game ** wins)
        outcomes.append(ScoreOutcome(wins_a=wins, wins_b=wins_needed, probability=prob))
    return outcomes
