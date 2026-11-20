#!/usr/bin/env python3
"""
player_ratings.py

Purpose:
Player-level Glicko-2 pipeline: rate individual account_ids instead of org
team_ids, so a transferred player's skill travels with them and a team's
predicted strength reflects whoever is actually in the lineup right now --
not just that org's historical win/loss record. This is what let us stop
guessing at TI2026's roster-continuity cases (Iron Wing = ex-Tundra Esports
players, LGD's TaiLung-for-Topson swap, etc.) instead of patching around
them with manual team_id overrides.

Mirrors ratings.py's period-batched design (see that module's docstring for
the inactivity-decay rationale, and glicko2.batch_update for the shared
update loop). The difference is purely in what counts as "the entity being
rated" and how a match's two competing ratings get built: a composite of 5
players' ratings instead of one team_id's rating.

Location:
    odds/player_ratings.py
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

from . import glicko2
from .data import load_matches
from .lineups import LineupData, MatchLineup, load_lineups


@dataclass
class PlayerPrediction:
    match_id: int
    start_time: int
    period: int
    prob_a: float  # model P(radiant composite wins), using pre-period ratings
    actual_a: float


@dataclass
class PlayerPipelineResult:
    states: dict
    last_period: dict
    latest_period: int
    predictions: list[PlayerPrediction] = field(default_factory=list)
    names: dict = field(default_factory=dict)
    current_lineup_by_team: dict = field(default_factory=dict)

    def effective_rating(self, account_id, as_of_period: int | None = None) -> glicko2.Rating:
        """Same inactivity-decay projection as ratings.PipelineResult, per player."""
        if account_id not in self.states:
            return glicko2.Rating.from_display()
        period = self.latest_period if as_of_period is None else as_of_period
        skipped = max(0, period - self.last_period[account_id])
        return self.states[account_id].with_inactivity(skipped)

    def team_rating(self, team_id: int, as_of_period: int | None = None) -> glicko2.Rating | None:
        """
        Composite rating for a team_id's most-recently-fielded lineup, or
        None if no lineup has ever been recorded for it.
        """
        account_ids = self.current_lineup_by_team.get(team_id)
        if not account_ids:
            return None
        return composite_rating([self.effective_rating(a, as_of_period) for a in account_ids])


def composite_rating(player_ratings: list[glicko2.Rating]) -> glicko2.Rating:
    """
    Combine several players' ratings into one team-strength rating for
    win-probability comparisons. Composites are read-only projections --
    they're never themselves passed to update_rating, only individual
    player ratings are.

    mu is the plain mean (average individual skill). phi is the root-mean-
    square of the players' own phi: a lineup is only as predictable as its
    least-certain player, not more certain just because there are five of
    them -- their phi's aren't independent samples of the same quantity the
    way a sqrt(5)-shrunk average would assume. This combination rule is a
    modeling choice, not part of the Glicko-2 spec; check run_backtest.py's
    calibration output before trusting it over the org-level model.
    """
    if not player_ratings:
        return glicko2.Rating.from_display()
    n = len(player_ratings)
    mu = sum(r.mu for r in player_ratings) / n
    phi = math.sqrt(sum(r.phi**2 for r in player_ratings) / n)
    sigma = sum(r.sigma for r in player_ratings) / n
    return glicko2.Rating(mu=mu, phi=phi, sigma=sigma)


def _catch_up(state: glicko2.Rating, last_period: int, target_period: int) -> glicko2.Rating:
    skipped = target_period - last_period - 1
    return state.with_inactivity(max(0, skipped))


def run_player_pipeline(lineup_data: LineupData, tau: float = glicko2.DEFAULT_TAU) -> PlayerPipelineResult:
    """
    Process matches period by period, updating individual player ratings.

    Every one of the 5 players on a side shares that side's outcome as
    their own game result, played against the composite of the other
    side's 5 pre-period ratings. A player who appears for two different
    teams within the same period (mid-period transfer, or a stand-in
    appearance) is simply credited/blamed for all of their games that
    period, same as any other period with multiple games.

    Args:
        lineup_data: Output of lineups.load_lineups.
        tau: Glicko-2 system volatility-change constant.

    Returns:
        PlayerPipelineResult with final per-player states, walk-forward
        predictions (no lookahead -- same guarantee as ratings.run_pipeline),
        and each team's most-recently-fielded lineup for composite lookups.
    """
    lineups = lineup_data.lineups
    states: dict = {}
    last_period: dict = {}
    predictions: list[PlayerPrediction] = []

    if not lineups:
        return PlayerPipelineResult(states=states, last_period=last_period, latest_period=0)

    by_period: dict[int, list[MatchLineup]] = {}
    for m in lineups:
        by_period.setdefault(m.period, []).append(m)

    for period in sorted(by_period.keys()):
        period_matches = by_period[period]

        pre_period: dict = {}
        for m in period_matches:
            for account_id in (*m.radiant_ids, *m.dire_ids):
                if account_id in pre_period:
                    continue
                if account_id in states:
                    pre_period[account_id] = _catch_up(states[account_id], last_period[account_id], period)
                else:
                    pre_period[account_id] = glicko2.Rating.from_display()

        opponents: dict = {}
        for m in period_matches:
            radiant_composite = composite_rating([pre_period[a] for a in m.radiant_ids])
            dire_composite = composite_rating([pre_period[a] for a in m.dire_ids])

            predictions.append(PlayerPrediction(
                match_id=m.match_id,
                start_time=m.start_time,
                period=period,
                prob_a=glicko2.expected_score(radiant_composite, dire_composite),
                actual_a=m.score_a,
            ))

            for account_id in m.radiant_ids:
                opponents.setdefault(account_id, []).append((dire_composite, m.score_a))
            for account_id in m.dire_ids:
                opponents.setdefault(account_id, []).append((radiant_composite, 1.0 - m.score_a))

        updated = glicko2.batch_update(pre_period, opponents, tau=tau)
        for account_id, rating in updated.items():
            states[account_id] = rating
            last_period[account_id] = period

    return PlayerPipelineResult(
        states=states,
        last_period=last_period,
        latest_period=max(by_period.keys()),
        predictions=predictions,
        names=lineup_data.player_names,
        current_lineup_by_team=lineup_data.current_lineup_by_team,
    )


def build_current_player_ratings(db_path: str, tau: float = glicko2.DEFAULT_TAU) -> PlayerPipelineResult:
    """
    Convenience entry point: load matches + cached lineups and run the full
    player-level pipeline in one call.

    Args:
        db_path: Path to dota.db (only used for the matches/outcomes side --
            lineups come from the data/derived/lineups.csv cache, see
            build_lineups.py).
        tau: Glicko-2 system volatility-change constant.

    Returns:
        PlayerPipelineResult with current ratings for every player seen.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        matches = load_matches(conn)
    finally:
        conn.close()
    lineup_data = load_lineups(matches)
    return run_player_pipeline(lineup_data, tau=tau)
