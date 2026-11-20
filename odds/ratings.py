#!/usr/bin/env python3
"""
ratings.py

Purpose:
Run the Glicko-2 pipeline over a chronological match list, one rating period
at a time, and expose the resulting team ratings plus the walk-forward
predictions generated along the way (pre-period ratings predicting that
period's outcomes -- no lookahead).

Roster-continuity note:
Ratings are keyed on OpenDota's team_id, which is an organization-level id,
not a roster-level one. A full roster shuffle under the same org (or a
partial one) is not modeled here -- the team simply keeps its rating and
accumulated history. Inactivity is handled: a team's RD (phi) grows for every
rating period it doesn't play, using the standard Glicko-2 no-outcomes update,
so a long-dormant team's rating carries more uncertainty when it resurfaces.
An org that rebrands under a new team_id starts fresh, which is usually the
right call since OpenDota already treats that as a new team.

Location:
    odds/ratings.py
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from . import glicko2
from .data import MatchRow, latest_team_names, load_matches


@dataclass
class Prediction:
    match_id: int
    start_time: int
    period: int
    team_a: int
    team_b: int
    prob_a: float  # model P(team_a wins), using pre-period ratings
    actual_a: float  # 1.0 / 0.0


@dataclass
class PipelineResult:
    states: dict[int, glicko2.Rating]
    last_period: dict[int, int]
    latest_period: int
    predictions: list[Prediction] = field(default_factory=list)
    names: dict[int, str] = field(default_factory=dict)

    def effective_rating(self, team_id: int, as_of_period: int | None = None) -> glicko2.Rating:
        """
        Return a team's rating with inactivity decay applied up to
        `as_of_period` (defaults to the latest period processed).

        This does not mutate stored state -- it's a read-only projection,
        so it's safe to call repeatedly for display or for what-if queries.
        """
        if team_id not in self.states:
            return glicko2.Rating.from_display()
        period = self.latest_period if as_of_period is None else as_of_period
        skipped = max(0, period - self.last_period[team_id])
        return self.states[team_id].with_inactivity(skipped)


def _catch_up(state: glicko2.Rating, last_period: int, target_period: int) -> glicko2.Rating:
    skipped = target_period - last_period - 1
    return state.with_inactivity(max(0, skipped))


def run_pipeline(matches: list[MatchRow], tau: float = glicko2.DEFAULT_TAU) -> PipelineResult:
    """
    Process matches period by period, updating team ratings with Glicko-2.

    Within a rating period, every team's games are batched into a single
    update using pre-period ratings for both sides (matching the Glicko-2
    spec: opponents' ratings don't move mid-period). Predictions are
    collected using those same pre-period ratings, so they're a genuine
    walk-forward evaluation.

    Args:
        matches: Chronologically sorted MatchRow list.
        tau: Glicko-2 system volatility-change constant.

    Returns:
        PipelineResult with final per-team states and all walk-forward
        predictions made along the way.
    """
    states: dict[int, glicko2.Rating] = {}
    last_period: dict[int, int] = {}
    predictions: list[Prediction] = []

    if not matches:
        return PipelineResult(states=states, last_period=last_period, latest_period=0)

    by_period: dict[int, list[MatchRow]] = {}
    for m in matches:
        by_period.setdefault(m.period, []).append(m)

    for period in sorted(by_period.keys()):
        period_matches = by_period[period]

        # Snapshot every participating team's pre-period effective rating
        # once, so all games this period (including rematches) compare
        # against the same starting point.
        pre_period: dict[int, glicko2.Rating] = {}
        for m in period_matches:
            for team_id in (m.team_a, m.team_b):
                if team_id in pre_period:
                    continue
                if team_id in states:
                    pre_period[team_id] = _catch_up(states[team_id], last_period[team_id], period)
                else:
                    pre_period[team_id] = glicko2.Rating.from_display()

        # Predictions, then group each team's (opponent, score) list.
        opponents: dict[int, list[tuple[glicko2.Rating, float]]] = {}
        for m in period_matches:
            rating_a = pre_period[m.team_a]
            rating_b = pre_period[m.team_b]

            predictions.append(Prediction(
                match_id=m.match_id,
                start_time=m.start_time,
                period=period,
                team_a=m.team_a,
                team_b=m.team_b,
                prob_a=glicko2.expected_score(rating_a, rating_b),
                actual_a=m.score_a,
            ))

            opponents.setdefault(m.team_a, []).append((rating_b, m.score_a))
            opponents.setdefault(m.team_b, []).append((rating_a, 1.0 - m.score_a))

        updated = glicko2.batch_update(pre_period, opponents, tau=tau)
        for team_id, rating in updated.items():
            states[team_id] = rating
            last_period[team_id] = period

    names = latest_team_names(matches)
    return PipelineResult(
        states=states,
        last_period=last_period,
        latest_period=max(by_period.keys()),
        predictions=predictions,
        names=names,
    )


def build_current_ratings(db_path: str, tau: float = glicko2.DEFAULT_TAU) -> PipelineResult:
    """
    Convenience entry point: load matches from the DB and run the full
    pipeline in one call.

    Args:
        db_path: Path to dota.db.
        tau: Glicko-2 system volatility-change constant.

    Returns:
        PipelineResult with current ratings for every team seen.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        matches = load_matches(conn)
    finally:
        conn.close()
    return run_pipeline(matches, tau=tau)


def win_probability(result: PipelineResult, team_a: int, team_b: int) -> float:
    """
    Current model win probability for team_a over team_b, using each team's
    effective (inactivity-decayed) rating as of the latest period processed.
    """
    rating_a = result.effective_rating(team_a)
    rating_b = result.effective_rating(team_b)
    return glicko2.expected_score(rating_a, rating_b)
