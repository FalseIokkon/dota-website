#!/usr/bin/env python3
"""
find_ev_bets.py

Purpose:
Compare current Glicko-2 win probabilities against a manually-maintained
moneyline odds sheet and flag +EV bets. TI2026 odds aren't live yet -- this
reads whatever's in the input CSV, so it's a no-op until that file has rows.

Uses the player-composite model (player_ratings.py), not each org's own
win/loss history -- run_backtest.py --model both showed it's the better
predictor on real match data (lower Brier score and log loss than the
org-level model). Ratings come from whoever's actually in a team's current
lineup, patched by any TI2026_LINEUP_OVERRIDES for personnel changes too
recent to have match data yet (see odds/ti2026_teams.py).

Input format (data/raw/ti2026_odds.csv), one row per matchup per bookmaker:
    team_a,team_b,odds_a,odds_b,bookmaker
    Team Falcons,Gaimin Gladiators,-150,+130,Pinnacle

odds_a/odds_b are for team_a/team_b winning the match -- American, decimal,
or a prediction-market price like 0.58 (auto-detected per value, see
ev.parse_odds), so you can type numbers straight off a sportsbook's American
odds board, or a Polymarket/Kalshi share price, without converting by hand.
Fill this in by hand once sportsbooks (or a prediction market) post TI2026 lines.

Location:
    odds/find_ev_bets.py
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DB_PATH  # noqa: E402
from odds.ev import evaluate_moneyline, expected_value, format_american, parse_odds  # noqa: E402
from odds.hero_adjustment import adjust_probability  # noqa: E402
from odds.hero_affinity import compute_hero_affinity, top_heroes  # noqa: E402
from odds.hero_meta import compute_hero_meta  # noqa: E402
from odds.player_ratings import build_current_player_ratings, composite_rating  # noqa: E402
from odds.ratings import build_current_ratings  # noqa: E402
from odds.ti2026_teams import apply_lineup_overrides, resolve_team_id  # noqa: E402

DEFAULT_INPUT_PATH = REPO_ROOT / "data" / "raw" / "ti2026_odds.csv"
EXPORT_DIR = REPO_ROOT / "data" / "exports" / "odds"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Flag +EV bets from an odds CSV against model ratings.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH, help="Path to the odds CSV.")
    parser.add_argument("--min-edge", type=float, default=0.0, help="Minimum conservative EV per unit staked to flag a bet (default 0.0 = any +EV).")
    parser.add_argument("--save", action="store_true", help="Also write results to data/exports/odds/.")
    parser.add_argument(
        "--with-hero-fit",
        action="store_true",
        help=(
            "Also show a hero-fit-adjusted probability/EV, using each player's single most-played "
            "hero as a pre-draft proxy for what they'll likely pick (see odds/hero_adjustment.py). "
            "Heuristic, not yet backtested -- treat as directional."
        ),
    )
    return parser.parse_args()


def _top_hero_id(account_id, affinity: dict) -> int | None:
    stats = top_heroes(account_id, affinity, n=1)
    return stats[0].hero_id if stats else None


def main() -> None:
    args = parse_args()

    if not args.input.exists():
        print(f"No odds file at {args.input}. Create it with columns: team_a,team_b,odds_a,odds_b,bookmaker")
        return

    # Org-level result is kept only for its team_id -> name map (needed to
    # resolve odds-sheet team names via resolve_team_id); the ratings
    # actually used come from the player-composite model below.
    result = build_current_ratings(str(DB_PATH))
    player_result = build_current_player_ratings(str(DB_PATH))

    affinity = compute_hero_affinity(str(DB_PATH)) if args.with_hero_fit else None
    hero_meta_stats = compute_hero_meta(str(DB_PATH)) if args.with_hero_fit else None

    all_evals = []
    with args.input.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            lookup_a = resolve_team_id(row["team_a"], result.names)
            lookup_b = resolve_team_id(row["team_b"], result.names)

            if lookup_a.team_id is None or lookup_b.team_id is None:
                bad = lookup_a if lookup_a.team_id is None else lookup_b
                unresolved = row["team_a"] if lookup_a.team_id is None else row["team_b"]
                if bad.confidence == "ambiguous":
                    print(f"[WARN] {unresolved!r} matches multiple teams: {', '.join(bad.candidates)} -- skipping row.")
                else:
                    print(f"[WARN] Could not resolve team name to a rated team: {unresolved!r} -- skipping row.")
                continue

            lineup_a = player_result.current_lineup_by_team.get(lookup_a.team_id)
            lineup_b = player_result.current_lineup_by_team.get(lookup_b.team_id)
            if not lineup_a or not lineup_b:
                unresolved = row["team_a"] if not lineup_a else row["team_b"]
                print(f"[WARN] No cached lineup for {unresolved!r} -- skipping row.")
                continue

            patched_a = apply_lineup_overrides(lookup_a.canonical or row["team_a"], lineup_a)
            patched_b = apply_lineup_overrides(lookup_b.canonical or row["team_b"], lineup_b)
            if patched_a != lineup_a:
                print(f"[INFO] Applied manual lineup override for {row['team_a']!r}")
            if patched_b != lineup_b:
                print(f"[INFO] Applied manual lineup override for {row['team_b']!r}")
            lineup_a, lineup_b = patched_a, patched_b

            rating_a = composite_rating([player_result.effective_rating(acc) for acc in lineup_a])
            rating_b = composite_rating([player_result.effective_rating(acc) for acc in lineup_b])

            odds_a = parse_odds(row["odds_a"])
            odds_b = parse_odds(row["odds_b"])

            evals = evaluate_moneyline(
                team_a_name=row["team_a"],
                team_b_name=row["team_b"],
                odds_a=odds_a,
                odds_b=odds_b,
                rating_a=rating_a,
                rating_b=rating_b,
            )
            eval_dicts = [e.__dict__.copy() for e in evals]

            if args.with_hero_fit:
                team_a_picks = [(acc, _top_hero_id(acc, affinity)) for acc in lineup_a]
                team_b_picks = [(acc, _top_hero_id(acc, affinity)) for acc in lineup_b]
                base_prob_a = eval_dicts[0]["model_prob"]
                adjusted_prob_a = adjust_probability(base_prob_a, team_a_picks, team_b_picks, affinity, hero_meta_stats)
                adjusted_probs = (adjusted_prob_a, 1.0 - adjusted_prob_a)
                for e_dict, prob, odds in zip(eval_dicts, adjusted_probs, (odds_a, odds_b)):
                    e_dict["hero_adjusted_prob"] = prob
                    e_dict["hero_adjusted_ev"] = expected_value(prob, odds)

            for e_dict in eval_dicts:
                e_dict["bookmaker"] = row.get("bookmaker", "")
                all_evals.append(e_dict)

    if not all_evals:
        print("No evaluable rows found (empty input or all teams unresolved).")
        return

    all_evals.sort(key=lambda e: e["conservative_ev"], reverse=True)

    flagged = [e for e in all_evals if e["is_positive_ev"] and e["conservative_ev"] >= args.min_edge]

    header = f"{'Team':22s} {'vs':22s} {'Odds':>6s} {'Model%':>7s} {'Fair%':>7s} {'Edge':>7s} {'EV':>7s} {'ConsEV':>7s} {'Kelly':>6s}"
    if args.with_hero_fit:
        header += f" {'HeroAdj%':>8s} {'HeroEV':>7s}"
    header += "  Book"
    print(header)

    for e in all_evals:
        flag = "  <-- +EV" if e["is_positive_ev"] and e["conservative_ev"] >= args.min_edge else ""
        line = (
            f"{e['team'][:22]:22s} {e['opponent'][:22]:22s} {format_american(e['decimal_odds']):>6s} "
            f"{e['model_prob']*100:6.1f}% {e['fair_market_prob']*100:6.1f}% {e['edge']*100:6.1f}% "
            f"{e['ev']:7.3f} {e['conservative_ev']:7.3f} {e['kelly']*100:5.1f}%"
        )
        if args.with_hero_fit:
            line += f" {e['hero_adjusted_prob']*100:7.1f}% {e['hero_adjusted_ev']:7.3f}"
        line += f"  {e['bookmaker']}{flag}"
        print(line)

    if args.with_hero_fit:
        print("\nHeroAdj%/HeroEV use each player's most-played hero as a pre-draft proxy -- "
              "unvalidated heuristic (see odds/hero_adjustment.py), treat as directional only.")

    print()
    print(f"{len(flagged)} bet(s) clear +EV even under the conservative (RD-discounted) probability.")

    if args.save:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = EXPORT_DIR / f"ev_bets_{stamp}.csv"
        with out_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_evals[0].keys()))
            writer.writeheader()
            writer.writerows(all_evals)
        print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
