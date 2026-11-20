#!/usr/bin/env python3
"""
tournament_simulator.py

Purpose:
Estimate each TI2026 team's probability of winning the *entire tournament*
(not a single match) via Monte Carlo simulation of the full format: a Swiss
group stage feeding into an 8-team double-elimination bracket. Match-level
win probability (player_ratings.composite_rating + glicko2.expected_score)
doesn't answer "who wins the whole thing" directly -- that requires actually
simulating the bracket many times and counting outcomes.

Format (from Liquipedia, TI2026): 16 teams, Swiss group stage, all matches
Bo3. Top 3 Swiss finishers advance directly to playoffs. 4th-13th (10 teams)
play a single-elimination "elimination round" (Bo3) for the remaining 5
playoff spots (5 matches, 5 winners advance). 14th-16th are eliminated.
Playoffs: standard 8-team double-elimination bracket, all series Bo3 in this
simulation (a simplification -- see below).

Round 1 pairings are the actual announced bracket (confirmed via the live
Liquipedia bracket page, not simulated) -- see REAL_ROUND_1_PAIRINGS. Rounds
2-5 pair teams within each same-record group (confirmed from the same
bracket page: e.g. round 3 groups into 2-0/1-1/0-2 pools), using a seeded
fold (highest-rated vs lowest-rated within the group) rather than randomly,
avoiding an immediate rematch where possible.

Known approximations (Liquipedia's exact tiebreak/seeding algorithm within
each record group is Buchholz-style and we got rate-limited re-fetching the
precise rule text to check -- see the rest of this project's Liquipedia
interactions for why we don't hammer retries there):
  - Within-group pairing uses our own rating as the seed (fold pairing),
    not Valve's actual seeding criteria (likely qualification path /
    Buchholz score), so which *specific* two teams meet within a record
    group can differ from the real bracket even though the record-group
    structure itself is confirmed accurate.
  - Fixed at 5 Swiss rounds (confirmed from the bracket page, which shows
    exactly 5 rounds).
  - All playoff series are Bo3, including the Grand Final (real TI Grand
    Finals are typically Bo5) -- series length affects variance/upset rate
    more than which team is expected to win on average, so this shouldn't
    meaningfully bias *who* wins most often across many simulations.
  - Playoff seeding uses final Swiss standing in the classic 8-team
    double-elim template (1v8, 4v5, 3v6, 2v7 in the upper bracket).

Treat outright win probabilities as directional estimates for comparing
against futures-market odds, not as precise as the validated single-match
model.

Location:
    odds/tournament_simulator.py
"""

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DB_PATH  # noqa: E402
from odds import glicko2  # noqa: E402
from odds.ev import devig_multiplicative, expected_value, format_american, parse_odds  # noqa: E402
from odds.player_ratings import build_current_player_ratings, composite_rating  # noqa: E402
from odds.ratings import build_current_ratings  # noqa: E402
from odds.ti2026_teams import TI2026_TEAMS, apply_lineup_overrides, resolve_team_id  # noqa: E402

SWISS_ROUNDS = 5
DIRECT_QUALIFIERS = 3
ELIMINATION_ROUND_SPOTS = 10  # 4th-13th
PLAYOFF_SIZE = 8

# The actual announced Round 1 pairings (confirmed via the live Liquipedia
# bracket page, 2026-08-11) -- not simulated/guessed.
REAL_ROUND_1_PAIRINGS = [
    ("Team Falcons", "LGD Gaming"),
    ("Nigma Galaxy", "Iron Wing TI 2026"),
    ("BetBoom Team", "OG"),
    ("TEAM VISION", "Team Resilience"),
    ("Team Spirit", "Xtreme Gaming"),
    ("Team Liquid", "Vici Gaming"),
    ("Aurora Gaming", "GamerLegion"),
    ("Team Yandex", "HULIGANI"),
]


def build_team_ratings() -> dict[str, glicko2.Rating]:
    result = build_current_ratings(str(DB_PATH))
    player_result = build_current_player_ratings(str(DB_PATH))

    ratings: dict[str, glicko2.Rating] = {}
    for name in TI2026_TEAMS:
        lookup = resolve_team_id(name, result.names)
        if lookup.team_id is None:
            print(f"[WARN] Could not resolve {name!r} -- excluding from simulation.")
            continue
        lineup = player_result.current_lineup_by_team.get(lookup.team_id)
        if not lineup:
            print(f"[WARN] No cached lineup for {name!r} -- excluding from simulation.")
            continue
        lineup = apply_lineup_overrides(lookup.canonical or name, lineup)
        ratings[name] = composite_rating([player_result.effective_rating(a) for a in lineup])
    return ratings


def simulate_bo3(rating_a: glicko2.Rating, rating_b: glicko2.Rating) -> bool:
    """Returns True if side A wins the best-of-3."""
    wins_a = wins_b = 0
    prob_a = glicko2.expected_score(rating_a, rating_b)
    while wins_a < 2 and wins_b < 2:
        if random.random() < prob_a:
            wins_a += 1
        else:
            wins_b += 1
    return wins_a == 2


def fold_pair(group: list[str], ratings: dict[str, glicko2.Rating], played_pairs: set) -> list[tuple[str, str]]:
    """
    Pair a same-record group by seed fold: highest-rated vs lowest-rated,
    2nd-highest vs 2nd-lowest, etc. (confirmed from the bracket page that
    within-group pairing is a real seeding, not a free draw -- see module
    docstring for what's still an approximation about it). Swaps to avoid
    an immediate rematch where an alternative exists.
    """
    ranked = sorted(group, key=lambda t: ratings[t].mu, reverse=True)
    n = len(ranked)
    pairings = []
    used = set()
    for i in range(n // 2):
        a = ranked[i]
        if a in used:
            continue
        b = ranked[n - 1 - i]
        if b in used:
            # find the lowest-ranked unused team instead
            b = next(t for t in reversed(ranked) if t not in used and t != a)
        if (a, b) in played_pairs or (b, a) in played_pairs:
            alt = next((t for t in reversed(ranked) if t not in used and t not in (a, b)
                        and (a, t) not in played_pairs and (t, a) not in played_pairs), None)
            if alt is not None:
                b = alt
        pairings.append((a, b))
        used.add(a)
        used.add(b)
    return pairings


def run_swiss(teams: list[str], ratings: dict[str, glicko2.Rating]) -> list[str]:
    """Returns all 16 teams ranked best-to-worst by final Swiss standing."""
    record = {t: [0, 0] for t in teams}
    played_pairs: set = set()

    for round_num in range(SWISS_ROUNDS):
        if round_num == 0:
            pairings = list(REAL_ROUND_1_PAIRINGS)
        else:
            groups: dict[tuple, list[str]] = {}
            for t in teams:
                groups.setdefault(tuple(record[t]), []).append(t)
            pairings = []
            for group in groups.values():
                pairings.extend(fold_pair(group, ratings, played_pairs))

        for a, b in pairings:
            played_pairs.add((a, b))
            if simulate_bo3(ratings[a], ratings[b]):
                record[a][0] += 1
                record[b][1] += 1
            else:
                record[b][0] += 1
                record[a][1] += 1

    return sorted(teams, key=lambda t: (-record[t][0], record[t][1], random.random()))


def run_elimination_round(candidates: list[str], ratings: dict[str, glicko2.Rating]) -> list[str]:
    """10 teams (already ranked 4th-13th), paired 1v10/2v9/.../5v6; 5 winners advance."""
    winners = []
    n = len(candidates)
    for i in range(n // 2):
        a, b = candidates[i], candidates[n - 1 - i]
        winners.append(a if simulate_bo3(ratings[a], ratings[b]) else b)
    return winners


def run_playoffs(seeded: list[str], ratings: dict[str, glicko2.Rating]) -> str:
    """Standard 8-team double-elimination bracket, seeded 1-8. Returns the champion."""
    s = seeded  # s[0] = seed 1, ... s[7] = seed 8

    def play(a, b):
        return a if simulate_bo3(ratings[a], ratings[b]) else b

    def loser(a, b, winner):
        return b if winner == a else a

    # Upper bracket round 1
    ub_r1 = [(s[0], s[7]), (s[3], s[4]), (s[2], s[5]), (s[1], s[6])]
    ub_r1_winners = [play(a, b) for a, b in ub_r1]
    ub_r1_losers = [loser(a, b, w) for (a, b), w in zip(ub_r1, ub_r1_winners)]

    # Upper bracket semifinals
    ub_sf = [(ub_r1_winners[0], ub_r1_winners[1]), (ub_r1_winners[2], ub_r1_winners[3])]
    ub_sf_winners = [play(a, b) for a, b in ub_sf]
    ub_sf_losers = [loser(a, b, w) for (a, b), w in zip(ub_sf, ub_sf_winners)]

    # Upper bracket final
    ub_final_winner = play(ub_sf_winners[0], ub_sf_winners[1])
    ub_final_loser = loser(ub_sf_winners[0], ub_sf_winners[1], ub_final_winner)

    # Lower bracket round 1: UB R1 losers play each other
    lb_r1 = [(ub_r1_losers[0], ub_r1_losers[1]), (ub_r1_losers[2], ub_r1_losers[3])]
    lb_r1_winners = [play(a, b) for a, b in lb_r1]

    # Lower bracket round 2: LB R1 winners vs UB semifinal losers
    lb_r2 = [(lb_r1_winners[0], ub_sf_losers[0]), (lb_r1_winners[1], ub_sf_losers[1])]
    lb_r2_winners = [play(a, b) for a, b in lb_r2]

    # Lower bracket round 3: the 2 LB R2 winners play each other
    lb_r3_winner = play(lb_r2_winners[0], lb_r2_winners[1])

    # Lower bracket final: LB R3 winner vs the upper bracket final's loser
    # (who drops all the way to this last LB round, the standard 8-team
    # double-elim drop point for a UB finalist)
    lb_champion = play(lb_r3_winner, ub_final_loser)

    # Grand final
    champion = play(ub_final_winner, lb_champion)
    return champion


def simulate_tournament(teams: list[str], ratings: dict[str, glicko2.Rating]) -> str:
    ranked = run_swiss(teams, ratings)
    direct = ranked[:DIRECT_QUALIFIERS]
    elimination_candidates = ranked[DIRECT_QUALIFIERS:DIRECT_QUALIFIERS + ELIMINATION_ROUND_SPOTS]
    elimination_winners = run_elimination_round(elimination_candidates, ratings)
    playoff_field = direct + elimination_winners  # already in strength order -> valid seeding
    return run_playoffs(playoff_field, ratings)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monte Carlo TI2026 outright-winner simulation.")
    parser.add_argument("--trials", type=int, default=20000, help="Number of simulated tournaments (default 20000).")
    parser.add_argument(
        "--odds", nargs="+", metavar="TEAM=ODDS",
        help="Market odds to compare against, e.g. --odds \"Team Falcons=900\" \"TEAM VISION=300\". "
             "American, decimal, or a prediction-market price (auto-detected).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    random.seed()

    print("Loading ratings...")
    ratings = build_team_ratings()
    teams = list(ratings.keys())
    print(f"{len(teams)} teams loaded. Running {args.trials} simulated tournaments...")

    wins: Counter = Counter()
    for _ in range(args.trials):
        champion = simulate_tournament(teams, ratings)
        wins[champion] += 1

    results = [(t, wins.get(t, 0) / args.trials) for t in teams]
    results.sort(key=lambda r: r[1], reverse=True)

    market_odds = {}
    if args.odds:
        for entry in args.odds:
            name, _, odds_str = entry.partition("=")
            market_odds[name.strip()] = parse_odds(odds_str.strip())

    header = f"{'Team':22s} {'Win%':>7s} {'Fair Odds':>10s}"
    if market_odds:
        header += f" {'Market Odds':>12s} {'Market Fair%':>13s} {'Edge':>7s} {'EV':>7s}"
    print(header)

    flagged = []
    for team, prob in results:
        fair_odds = format_american(1.0 / prob) if prob > 0 else "n/a"
        line = f"{team[:22]:22s} {prob*100:6.2f}% {fair_odds:>10s}"
        if market_odds:
            odds = market_odds.get(team)
            if odds is None:
                line += "  (no market odds given)"
            else:
                # devig isn't well-defined for a >2-way outright market from
                # a single team's price alone, so this just compares our
                # probability against the market's own implied probability
                # (1/odds) directly -- no vig removal across all 16 teams.
                market_implied = 1.0 / odds
                edge = prob - market_implied
                ev = expected_value(prob, odds)
                flag = "  <-- +EV" if ev > 0 else ""
                line += f" {format_american(odds):>12s} {market_implied*100:12.2f}% {edge*100:6.2f}% {ev:+.3f}{flag}"
                if ev > 0:
                    flagged.append((team, ev))
        print(line)

    if market_odds:
        print()
        if flagged:
            print(f"{len(flagged)} team(s) show positive EV against the given market odds:")
            for team, ev in sorted(flagged, key=lambda x: -x[1]):
                print(f"  {team}: EV {ev:+.3f} per unit staked")
        else:
            print("No team shows positive EV against the given market odds.")
        print("\nNote: outright market prices always sum to well over 100% (multi-way overround) -- "
              "this compares our probability against each team's own implied probability directly, "
              "not a fully devigged market-wide fair probability.")


if __name__ == "__main__":
    main()
