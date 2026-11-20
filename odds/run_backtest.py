#!/usr/bin/env python3
"""
run_backtest.py

Purpose:
Check whether a rating pipeline's win probabilities are actually calibrated
against real outcomes, using the walk-forward predictions generated during
the same pass that updates ratings (no lookahead). Can score the org-level
model (ratings.py), the player-composite model (player_ratings.py), or both
side by side -- the comparison is the actual evidence for whether tracking
individual players is worth the extra complexity, rather than just assuming
it helps.

Location:
    odds/run_backtest.py
"""

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DB_PATH  # noqa: E402
from odds.backtest import DEFAULT_WARMUP_PERIODS, _eligible, brier_score, calibration_table, log_loss  # noqa: E402
from odds.data import load_matches  # noqa: E402
from odds.lineups import load_lineups  # noqa: E402
from odds.player_ratings import run_player_pipeline  # noqa: E402
from odds.ratings import run_pipeline  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest rating model(s) against real outcomes.")
    parser.add_argument(
        "--model", choices=["team", "player", "both"], default="team",
        help="Which model to score: org-level history (team), player-composite (player), or both (default: team).",
    )
    return parser.parse_args()


def report(label: str, preds: list) -> None:
    scored = _eligible(preds, DEFAULT_WARMUP_PERIODS)
    print(f"=== {label} ===")
    print(f"Predictions scored (post-warmup, {DEFAULT_WARMUP_PERIODS} periods dropped): {len(scored)}")
    print(f"Brier score: {brier_score(preds):.4f}  (0.25 = coin flip, 0.0 = perfect)")
    print(f"Log loss:    {log_loss(preds):.4f}  (0.693 = coin flip, 0.0 = perfect)")
    print()
    print(f"{'Pred range':>14s} {'n':>7s} {'mean pred':>10s} {'actual win%':>12s}")
    for b in calibration_table(preds):
        if b.n == 0:
            continue
        print(f"{b.low:5.2f}-{b.high:5.2f}    {b.n:7d} {b.mean_predicted:10.3f} {b.actual_win_rate:12.3f}")
    print()


def main() -> None:
    args = parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    matches = load_matches(conn)
    conn.close()
    print(f"Matches used: {len(matches)}")
    print()

    if args.model in ("team", "both"):
        team_result = run_pipeline(matches)
        report("Org-level (team_id history)", team_result.predictions)

    if args.model in ("player", "both"):
        lineup_data = load_lineups(matches)
        print(f"Matches with a cached lineup: {len(lineup_data.lineups)}/{len(matches)}")
        player_result = run_player_pipeline(lineup_data)
        report("Player-composite (current lineup)", player_result.predictions)


if __name__ == "__main__":
    main()
