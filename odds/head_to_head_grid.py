#!/usr/bin/env python3
"""
head_to_head_grid.py

Purpose:
Print/save a full pairwise win-probability grid for every TI2026 team
against every other one, using the player-composite model -- the one
validated (via run_backtest.py --model both) as the better predictor of the
two rating models in this project. Skill-only: no hero picks factored in.
For a specific matchup with hero picks, use live_draft.py; for a pre-draft
hero-fit estimate on a single matchup, use find_ev_bets.py --with-hero-fit.

Location:
    odds/head_to_head_grid.py
"""

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DB_PATH  # noqa: E402
from odds import glicko2  # noqa: E402
from odds.ev import format_american  # noqa: E402
from odds.player_ratings import build_current_player_ratings, composite_rating  # noqa: E402
from odds.ratings import build_current_ratings  # noqa: E402
from odds.ti2026_teams import TI2026_TEAMS, apply_lineup_overrides, resolve_team_id  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "data" / "derived" / "head_to_head_grid.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pairwise win-probability grid for TI2026 teams.")
    parser.add_argument("--teams", nargs="+", help="Optional subset of team names (default: all TI2026 teams).")
    parser.add_argument(
        "--matchups", nargs="+", metavar="TEAM_A vs TEAM_B",
        help="Print only these specific pairs (each as one 'Team A vs Team B' argument) with fair "
             "American odds, instead of the full grid, e.g. --matchups \"Team Falcons vs LGD Gaming\".",
    )
    return parser.parse_args()


def build_ratings(team_names: list[str]) -> dict[str, glicko2.Rating]:
    result = build_current_ratings(str(DB_PATH))
    player_result = build_current_player_ratings(str(DB_PATH))

    ratings: dict[str, glicko2.Rating] = {}
    for name in team_names:
        lookup = resolve_team_id(name, result.names)
        if lookup.team_id is None:
            if lookup.confidence == "ambiguous":
                print(f"[WARN] {name!r} matches multiple teams: {', '.join(lookup.candidates)} -- skipping.")
            else:
                print(f"[WARN] Could not resolve {name!r} -- skipping.")
            continue
        lineup = player_result.current_lineup_by_team.get(lookup.team_id)
        if not lineup:
            print(f"[WARN] No cached lineup for {name!r} -- skipping.")
            continue
        lineup = apply_lineup_overrides(lookup.canonical or name, lineup)
        ratings[name] = composite_rating([player_result.effective_rating(a) for a in lineup])
    return ratings


def short_labels_for(names: list[str]) -> dict[str, str]:
    """
    4-char column labels, deduped case-insensitively -- "Team Falcons" and
    "TEAM VISION" would otherwise both shorten to a near-identical "Team"/
    "TEAM", which is unreadable side by side in a fixed-width grid.
    """
    labels: dict[str, str] = {}
    used: set[str] = set()
    for name in names:
        base = name[:4]
        label, i = base, 1
        while label.lower() in used:
            label = f"{base[:3]}{i}"
            i += 1
        used.add(label.lower())
        labels[name] = label
    return labels


def print_matchups(matchups: list[str], team_names: list[str]) -> None:
    pairs = []
    for m in matchups:
        if " vs " not in m:
            print(f"[WARN] Skipping {m!r} -- expected 'Team A vs Team B'.")
            continue
        a, b = (s.strip() for s in m.split(" vs ", 1))
        pairs.append((a, b))
        for name in (a, b):
            if name not in team_names:
                team_names.append(name)

    ratings = build_ratings(team_names)

    print(f"{'Team A':22s} {'Team B':22s} {'A%':>6s} {'B%':>6s} {'A odds':>7s} {'B odds':>7s}")
    for a, b in pairs:
        if a not in ratings or b not in ratings:
            print(f"{a} vs {b}: unresolved, skipping.")
            continue
        prob_a = glicko2.expected_score(ratings[a], ratings[b])
        prob_b = 1.0 - prob_a
        odds_a = format_american(1.0 / prob_a) if prob_a > 0 else "n/a"
        odds_b = format_american(1.0 / prob_b) if prob_b > 0 else "n/a"
        print(f"{a[:22]:22s} {b[:22]:22s} {prob_a*100:5.1f}% {prob_b*100:5.1f}% {odds_a:>7s} {odds_b:>7s}")


def main() -> None:
    args = parse_args()
    team_names = args.teams or TI2026_TEAMS

    if args.matchups:
        print_matchups(args.matchups, list(team_names))
        return

    ratings = build_ratings(team_names)
    names = list(ratings.keys())
    if len(names) < 2:
        print("Need at least 2 resolvable teams to build a grid.")
        return

    labels = short_labels_for(names)
    col_width = max(len(l) for l in labels.values()) + 2

    print(f"\n{'':22s}" + "".join(f"{labels[n]:>{col_width}s}" for n in names))
    for row_name in names:
        cells = []
        for col_name in names:
            if row_name == col_name:
                cells.append(f"{'--':>{col_width}s}")
            else:
                prob = glicko2.expected_score(ratings[row_name], ratings[col_name])
                cells.append(f"{prob*100:{col_width-1}.0f}%")
        print(f"{row_name[:21]:22s}" + "".join(cells))

    print("\nRead as: row team's win probability against column team.")
    print("Legend:")
    for name in names:
        print(f"  {labels[name]:6s} = {name}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([""] + names)
        for row_name in names:
            row = [row_name]
            for col_name in names:
                if row_name == col_name:
                    row.append("")
                else:
                    row.append(f"{glicko2.expected_score(ratings[row_name], ratings[col_name]):.4f}")
            writer.writerow(row)
    print(f"\nSaved full grid to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
