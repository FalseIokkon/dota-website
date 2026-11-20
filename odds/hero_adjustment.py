#!/usr/bin/env python3
"""
hero_adjustment.py

Purpose:
Combine per-player hero affinity (hero_affinity.py) and current-patch hero
meta strength (hero_meta.py) into a single shift applied directly to a
match's win probability -- kept deliberately separate from the Glicko-2
composite rating (player_ratings.composite_rating), rather than folding into
player mu before compositing, so the long-run skill signal and the
per-draft hero signal can be shown side by side and reasoned about
independently.

Shared by two consumers: a pre-draft estimate (using each player's
most-played hero as a proxy for what they'll likely pick -- see
find_ev_bets.py's --with-hero-fit) and the live draft tool (using actual
picks as they're locked in -- see live_draft.py).

Caveat: the 1.0 scaling factor below (net fit differential applied
point-for-point to probability) is a starting heuristic, not a backtested
constant. Hero-level effects need far more current-patch match volume than
exists yet to validate properly the way run_backtest.py validated the base
player-composite model -- treat the hero-adjusted probability as directional,
not as precise as the unadjusted one.

Also folds in ban pressure: a hero banned constantly but occasionally let
through is a "the enemy team is scared of this hero" signal independent of
its own (possibly small, possibly biased-by-being-suppressed) observed win
rate -- see BAN_PRESSURE_WEIGHT.

Location:
    odds/hero_adjustment.py
"""

from __future__ import annotations

from dataclasses import dataclass

from .hero_affinity import PlayerHeroStat
from .hero_meta import HeroMeta

# Net (team_a_fit - team_b_fit) is added to the base probability at this
# scale. 1.0 = point-for-point (a +0.05 net fit shifts probability by 5
# percentage points). See module docstring -- unvalidated, tune once enough
# current-patch data exists to backtest.
ADJUSTMENT_SCALE = 1.0

# How much a hero's current-patch ban_rate contributes to its fit score, on
# top of win_rate_shrunk. E.g. a hero banned in 50% of games gets
# +0.5*BAN_PRESSURE_WEIGHT added regardless of its (possibly thin,
# possibly-biased-by-suppression) observed win rate when it does get
# played -- captains banning it is itself a "the field considers this
# hero dangerous" signal. Not centered against the average ban rate: with
# a fixed number of ban slots contested across 127 heroes, an actually
# neutral hero already sits near 0% naturally, so raw ban_rate
# differentiates real threats without needing rescaling. Unvalidated
# starting weight -- see module docstring's backtesting caveat.
BAN_PRESSURE_WEIGHT = 0.15

MIN_PROB = 0.01
MAX_PROB = 0.99


@dataclass
class HeroFitBreakdown:
    account_id: object
    hero_id: int | None
    affinity_delta: float
    meta_delta: float
    ban_pressure_delta: float
    total_fit: float


def player_hero_fit(
    account_id,
    hero_id: int | None,
    affinity: dict[tuple, PlayerHeroStat],
    hero_meta: dict[int, HeroMeta],
) -> HeroFitBreakdown:
    """
    A single player's hero-fit breakdown: how much they personally favor
    this hero (affinity_delta) plus how strong the hero is this patch
    (meta_delta), both in probability-point units.

    Args:
        account_id: The player's account_id.
        hero_id: Their drafted hero, or None if not picked/known yet.
        affinity: Output of hero_affinity.compute_hero_affinity.
        hero_meta: Output of hero_meta.compute_hero_meta.

    Returns:
        HeroFitBreakdown with all-zero deltas if hero_id is None, or if the
        hero has no data in either source (treated as neutral, not missing).
    """
    if hero_id is None:
        return HeroFitBreakdown(account_id, None, 0.0, 0.0, 0.0, 0.0)

    stat = affinity.get((account_id, hero_id))
    affinity_delta = stat.affinity_delta if stat else 0.0

    meta = hero_meta.get(hero_id)
    meta_delta = (meta.win_rate_shrunk - 0.5) if meta else 0.0
    ban_pressure_delta = (BAN_PRESSURE_WEIGHT * meta.ban_rate) if meta else 0.0

    return HeroFitBreakdown(
        account_id=account_id,
        hero_id=hero_id,
        affinity_delta=affinity_delta,
        meta_delta=meta_delta,
        ban_pressure_delta=ban_pressure_delta,
        total_fit=affinity_delta + meta_delta + ban_pressure_delta,
    )


def team_hero_fit(
    picks: list[tuple],
    affinity: dict[tuple, PlayerHeroStat],
    hero_meta: dict[int, HeroMeta],
) -> float:
    """
    A team's overall hero-fit score: mean fit across whichever picks have
    actually been locked in so far.

    Args:
        picks: List of (account_id, hero_id_or_None) for the team's known
            roster -- pass all 5 slots even mid-draft, with hero_id=None for
            anything not picked yet. Unfilled slots are excluded from the
            average entirely (not counted as 0), so a single confirmed pick
            carries its full weight immediately rather than being diluted
            by the 4 still-unknown slots -- the estimate should move as
            soon as real information exists, not wait for a full draft.
        affinity: Output of hero_affinity.compute_hero_affinity.
        hero_meta: Output of hero_meta.compute_hero_meta.

    Returns:
        Mean total_fit across filled picks, 0.0 if none are filled yet.
    """
    filled = [(acc, hero) for acc, hero in picks if hero is not None]
    if not filled:
        return 0.0
    total = sum(player_hero_fit(acc, hero, affinity, hero_meta).total_fit for acc, hero in filled)
    return total / len(filled)


def adjust_probability(
    base_prob_a: float,
    team_a_picks: list[tuple],
    team_b_picks: list[tuple],
    affinity: dict[tuple, PlayerHeroStat],
    hero_meta: dict[int, HeroMeta],
) -> float:
    """
    Shift a base Glicko-2 win probability by the net hero-fit differential
    between two teams.

    Args:
        base_prob_a: P(team_a wins) from the unadjusted Glicko-2 composite.
        team_a_picks, team_b_picks: Each team's (account_id, hero_id_or_None)
            list, see team_hero_fit.
        affinity: Output of hero_affinity.compute_hero_affinity.
        hero_meta: Output of hero_meta.compute_hero_meta.

    Returns:
        Adjusted P(team_a wins), clamped to [MIN_PROB, MAX_PROB].
    """
    fit_a = team_hero_fit(team_a_picks, affinity, hero_meta)
    fit_b = team_hero_fit(team_b_picks, affinity, hero_meta)
    adjusted = base_prob_a + ADJUSTMENT_SCALE * (fit_a - fit_b)
    return min(max(adjusted, MIN_PROB), MAX_PROB)
