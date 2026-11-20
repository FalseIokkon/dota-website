#!/usr/bin/env python3
"""
backtest.py

Purpose:
Score the walk-forward predictions produced by ratings.run_pipeline() against
what actually happened, so rating-model quality can be checked before it's
trusted for betting decisions. Pure scoring functions -- no DB access here.

Location:
    odds/backtest.py
"""

from __future__ import annotations

from dataclasses import dataclass

from .ratings import Prediction

# First few periods have almost no data (everyone is still at the 1500/350
# default), so their "predictions" are close to coin flips and would just
# dilute the calibration read. Skip them by default.
DEFAULT_WARMUP_PERIODS = 4


def _eligible(predictions: list[Prediction], warmup_periods: int) -> list[Prediction]:
    if not predictions:
        return []
    first_period = min(p.period for p in predictions)
    cutoff = first_period + warmup_periods
    return [p for p in predictions if p.period >= cutoff]


def brier_score(predictions: list[Prediction], warmup_periods: int = DEFAULT_WARMUP_PERIODS) -> float:
    """
    Mean squared error between predicted P(team_a wins) and the actual
    0/1 outcome. Lower is better; 0.25 is what an uninformative p=0.5
    model scores, 0.0 is a perfect model.
    """
    rows = _eligible(predictions, warmup_periods)
    if not rows:
        return float("nan")
    return sum((p.prob_a - p.actual_a) ** 2 for p in rows) / len(rows)


def log_loss(predictions: list[Prediction], warmup_periods: int = DEFAULT_WARMUP_PERIODS) -> float:
    """
    Mean binary cross-entropy loss. Lower is better; ln(2) ~= 0.693 is the
    score of an uninformative p=0.5 model.
    """
    import math

    rows = _eligible(predictions, warmup_periods)
    if not rows:
        return float("nan")

    eps = 1e-12
    total = 0.0
    for p in rows:
        prob = min(max(p.prob_a, eps), 1.0 - eps)
        total += -(p.actual_a * math.log(prob) + (1.0 - p.actual_a) * math.log(1.0 - prob))
    return total / len(rows)


@dataclass
class CalibrationBucket:
    low: float
    high: float
    n: int
    mean_predicted: float
    actual_win_rate: float


def calibration_table(
    predictions: list[Prediction],
    warmup_periods: int = DEFAULT_WARMUP_PERIODS,
    n_buckets: int = 10,
) -> list[CalibrationBucket]:
    """
    Bucket predictions by predicted probability and compare against realized
    win rate in each bucket. A well-calibrated model should have
    actual_win_rate ~= mean_predicted in every bucket.
    """
    rows = _eligible(predictions, warmup_periods)
    buckets: list[CalibrationBucket] = []
    width = 1.0 / n_buckets

    for i in range(n_buckets):
        low, high = i * width, (i + 1) * width
        in_bucket = [p for p in rows if low <= p.prob_a < high or (i == n_buckets - 1 and p.prob_a == high)]
        if not in_bucket:
            buckets.append(CalibrationBucket(low, high, 0, float("nan"), float("nan")))
            continue
        mean_pred = sum(p.prob_a for p in in_bucket) / len(in_bucket)
        win_rate = sum(p.actual_a for p in in_bucket) / len(in_bucket)
        buckets.append(CalibrationBucket(low, high, len(in_bucket), mean_pred, win_rate))

    return buckets
