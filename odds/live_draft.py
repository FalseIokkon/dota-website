#!/usr/bin/env python3
"""
live_draft.py

Purpose:
Interactive tool for typing in heroes as they're picked during a draft
you're watching live, showing an updated win probability after each entry.
Combines the unadjusted Glicko-2 composite (player_ratings.py) with the
hero-fit adjustment (hero_adjustment.py) so both numbers stay visible side
by side.

Roster slots are labeled with OpenDota's curated pro-player name where one
has been fetched (see player_names.py / fetch_player_names.py), falling
back to the raw Steam personaname otherwise -- that fallback is often a
joke/unrelated nickname, not a competitive handle. Run
`python3 odds/fetch_player_names.py` after any TI2026 roster change to keep
the curated-name cache current.

Location:
    odds/live_draft.py
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DB_PATH  # noqa: E402
from odds import glicko2  # noqa: E402
from odds.ev import devig_multiplicative, expected_value, format_american, kelly_fraction, parse_odds  # noqa: E402
from odds.hero_adjustment import adjust_probability, player_hero_fit  # noqa: E402
from odds.hero_affinity import compute_hero_affinity  # noqa: E402
from odds.hero_meta import compute_hero_meta, current_patch  # noqa: E402
from odds.hero_names import load_hero_names, resolve_hero  # noqa: E402
from odds.player_names import display_name, load_player_names  # noqa: E402
from odds.player_ratings import build_current_player_ratings, composite_rating  # noqa: E402
from odds.ratings import build_current_ratings  # noqa: E402
from odds.series import series_win_probability  # noqa: E402
from odds.ti2026_teams import apply_lineup_overrides, resolve_team_id  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live draft-time win probability tool.")
    parser.add_argument("team_a", help="Team A name (as it'd appear in odds/ti2026_teams.py or pro_matches).")
    parser.add_argument("team_b", help="Team B name.")
    parser.add_argument(
        "--odds", nargs=2, type=parse_odds, metavar=("ODDS_A", "ODDS_B"),
        help="Set a starting odds line, American, decimal, or a prediction-market price like 0.58 (auto-detected), shown from the very first "
             "status print instead of waiting for an 'odds' command, e.g. --odds -150 +130.",
    )
    parser.add_argument(
        "--best-of", type=int, default=3, metavar="N",
        help="Series length the 'odds' command's line is quoted on (default 3, a Bo3 'Match Winner' market -- "
             "TI2026's group stage and most playoff rounds). The hero-adjusted probability this tool tracks is "
             "inherently per-GAME (a specific draft only applies to the game it was drafted for), so it's "
             "converted to a per-series probability before comparing against the odds. Pass --best-of 1 if the "
             "line you're checking is actually single-game (e.g. a 'Map 1 Winner' market), which skips the "
             "conversion entirely.",
    )
    return parser.parse_args()


def resolve_roster(team_name: str, names: dict, player_result) -> tuple[int, list, str]:
    """
    Returns (team_id, lineup, display_label). display_label is always the
    resolved name (proper official casing, e.g. "OG"/"BoomBoys" even if
    you typed "og"/"boomboys") -- used for every subsequent print, not
    just the one-time match announcement, so whatever you typed shows up
    as the real name everywhere in the output afterward. A match
    announcement is only printed for non-trivial matches (alias/prefix/
    fuzzy); a case-insensitive exact match doesn't need one.
    """
    lookup = resolve_team_id(team_name, names)
    if lookup.team_id is None:
        if lookup.confidence == "ambiguous":
            print(f"{team_name!r} matches multiple teams: {', '.join(lookup.candidates)}. Be more specific.")
        else:
            print(f"Could not resolve team name to a rated team: {team_name!r}")
        sys.exit(1)

    display_label = lookup.canonical or lookup.matched_name or team_name
    if lookup.confidence in ("alias", "prefix", "fuzzy"):
        print(f"[INFO] {lookup.confidence}-matched {team_name!r} -> {display_label!r}")

    lineup = player_result.current_lineup_by_team.get(lookup.team_id)
    if not lineup:
        print(f"No cached lineup for {team_name!r} (team_id={lookup.team_id}).")
        sys.exit(1)
    patched = apply_lineup_overrides(lookup.canonical or team_name, lineup)
    if patched != lineup:
        print(f"[INFO] Applied manual lineup override for {display_label!r}")
    return lookup.team_id, patched, display_label


def print_status(
    team_a_label: str, team_a_ids: list, team_a_heroes: list,
    team_b_label: str, team_b_ids: list, team_b_heroes: list,
    base_prob_a: float, curated_names: dict, personaname_map: dict, hero_id_to_name: dict,
    affinity: dict, hero_meta_stats: dict,
) -> None:
    picks_a = list(zip(team_a_ids, team_a_heroes))
    picks_b = list(zip(team_b_ids, team_b_heroes))
    adjusted_prob_a = adjust_probability(base_prob_a, picks_a, picks_b, affinity, hero_meta_stats)

    fair_odds_a = 1.0 / adjusted_prob_a if adjusted_prob_a > 0 else float("inf")
    fair_odds_b = 1.0 / (1.0 - adjusted_prob_a) if adjusted_prob_a < 1 else float("inf")

    print(f"\nBase P({team_a_label} wins, per game) = {base_prob_a*100:5.1f}%   "
          f"Hero-adjusted (per game) = {adjusted_prob_a*100:5.1f}%   "
          f"(P({team_b_label} wins, per game) = {(1-adjusted_prob_a)*100:5.1f}%)")
    print(f"  Model fair odds (no market involved): {team_a_label} {format_american(fair_odds_a)}  |  "
          f"{team_b_label} {format_american(fair_odds_b)}")

    for team_offset, (label, ids, heroes) in enumerate(
        ((team_a_label, team_a_ids, team_a_heroes), (team_b_label, team_b_ids, team_b_heroes))
    ):
        print(f"  {label}:")
        for i, (acc, hero_id) in enumerate(zip(ids, heroes)):
            slot_num = team_offset * 5 + i
            name = display_name(acc, curated_names, personaname_map)
            prefix = f"    [{slot_num}] {name:<16s}:"
            if hero_id is None:
                print(f"{prefix} -- not picked --")
                continue
            fit = player_hero_fit(acc, hero_id, affinity, hero_meta_stats)
            hero_name = hero_id_to_name.get(hero_id, f"hero_{hero_id}")
            meta = hero_meta_stats.get(hero_id)
            ban_note = f", banned {meta.ban_rate*100:.0f}% of games" if meta and meta.ban_rate > 0 else ""
            print(f"{prefix} {hero_name:<20s} "
                  f"(affinity {fit.affinity_delta*100:+.1f}pp, patch-meta {fit.meta_delta*100:+.1f}pp, "
                  f"ban-pressure {fit.ban_pressure_delta*100:+.1f}pp{ban_note})")


def format_head_to_head(
    prob_a: float, odds_a: float, odds_b: float, label_a: str, label_b: str, best_of: int = 3,
) -> str:
    """
    A compact, side-by-side +EV comparison for a fixed odds line against the
    current (hero-adjusted) probability. Meant to be reprinted every time the
    probability changes, not just computed once, so a bookmaker line stays
    visibly "live" against the draft as it develops.

    `prob_a` is the per-GAME hero-adjusted probability (a specific draft only
    applies to the game it was drafted for). If `best_of` > 1 -- the normal
    case, since a "Match Winner" line is a full series -- it's converted to a
    per-series probability via series.series_win_probability before being
    compared against the odds, which are quoted on the series. Pass
    best_of=1 for an odds line that's actually single-game (e.g. "Map 1
    Winner"), which skips the conversion.
    """
    series_prob_a = series_win_probability(prob_a, best_of) if best_of > 1 else prob_a
    devig = devig_multiplicative(odds_a, odds_b)
    series_note = f" (Bo{best_of} series, converted from per-game {prob_a*100:.1f}%)" if best_of > 1 else " (single-game)"
    lines = [f"  Odds check -- {label_a}@{format_american(odds_a)} / {label_b}@{format_american(odds_b)}{series_note}:"]
    for label, prob, odds, fair in (
        (label_a, series_prob_a, odds_a, devig.fair_prob_a),
        (label_b, 1.0 - series_prob_a, odds_b, devig.fair_prob_b),
    ):
        ev = expected_value(prob, odds)
        kelly = kelly_fraction(prob, odds)
        fair_odds = 1.0 / prob if prob > 0 else float("inf")
        flag = "  <-- +EV" if ev > 0 else ""
        lines.append(f"    {label:20s} model {prob*100:5.1f}% (fair odds {format_american(fair_odds):>5s})  "
                     f"market fair {fair*100:5.1f}%  EV {ev:+.3f}  Kelly {kelly*100:4.1f}%{flag}")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()

    print("Loading ratings and hero data (a few seconds)...")
    result = build_current_ratings(str(DB_PATH))
    player_result = build_current_player_ratings(str(DB_PATH))
    affinity = compute_hero_affinity(str(DB_PATH))
    hero_meta_stats = compute_hero_meta(str(DB_PATH))
    hero_id_to_name = load_hero_names()
    curated_names = load_player_names()
    print(f"Current patch: {current_patch(str(DB_PATH))}")

    team_a_id, team_a_ids, team_a_label = resolve_roster(args.team_a, result.names, player_result)
    team_b_id, team_b_ids, team_b_label = resolve_roster(args.team_b, result.names, player_result)

    rating_a = composite_rating([player_result.effective_rating(a) for a in team_a_ids])
    rating_b = composite_rating([player_result.effective_rating(a) for a in team_b_ids])
    base_prob_a = glicko2.expected_score(rating_a, rating_b)

    team_a_heroes: list = [None] * 5
    team_b_heroes: list = [None] * 5

    current_odds: list = [tuple(args.odds) if args.odds else None]  # mutable cell so nested closures can update it

    def current_prob_a() -> float:
        picks_a = list(zip(team_a_ids, team_a_heroes))
        picks_b = list(zip(team_b_ids, team_b_heroes))
        return adjust_probability(base_prob_a, picks_a, picks_b, affinity, hero_meta_stats)

    def refresh() -> None:
        print_status(team_a_label, team_a_ids, team_a_heroes, team_b_label, team_b_ids, team_b_heroes,
                     base_prob_a, curated_names, player_result.names, hero_id_to_name, affinity, hero_meta_stats)
        if current_odds[0] is not None:
            print(format_head_to_head(current_prob_a(), *current_odds[0], team_a_label, team_b_label, args.best_of))

    print("\nHero-fit adjustment is a heuristic, not backtested -- treat as directional, not precise.")

    refresh()

    print("\nEnter picks as '<slot> <hero>', e.g. '0 Ursa' or '9 pa' (0-4 = Team A slots 1-5, 5-9 = Team B slots 1-5).")
    print("Type a slot number alone (e.g. '3') to clear that pick. Picking a hero already in use moves it.")
    print("Commands: 'odds <odds_a> <odds_b>' to set/update a line and see it head-to-head against every "
          "update -- American, decimal, or a prediction-market price like 0.58 (e.g. 'odds -150 +130' or "
          "'odds 0.58 0.44'); 'odds' alone to reprint it; 'done' to quit.\n")

    def team_context(slot_num: int):
        is_team_a = slot_num < 5
        heroes = team_a_heroes if is_team_a else team_b_heroes
        label = team_a_label if is_team_a else team_b_label
        return heroes, label, slot_num if is_team_a else slot_num - 5

    while True:
        raw = input("> ").strip()
        if not raw:
            continue
        if raw.lower() in ("done", "quit", "exit"):
            break
        if raw.lower() == "odds" or raw.lower().startswith("odds "):
            tokens = raw.split()
            if len(tokens) == 3:
                try:
                    current_odds[0] = (parse_odds(tokens[1]), parse_odds(tokens[2]))
                except ValueError:
                    print("  Usage: odds <odds_a> <odds_b> (American, decimal, or a price like 0.58), e.g. 'odds -150 +130'")
                    continue
            elif len(tokens) != 1:
                print("  Usage: odds <odds_a> <odds_b> (American, decimal, or a price like 0.58), e.g. 'odds -150 +130'")
                continue

            if current_odds[0] is None:
                print("  No odds set yet. Usage: odds <odds_a> <odds_b>")
                continue
            print(format_head_to_head(current_prob_a(), *current_odds[0], team_a_label, team_b_label, args.best_of))
            continue

        parts = raw.split(maxsplit=1)
        slot_token = parts[0]
        if not slot_token.isdigit() or not (0 <= int(slot_token) <= 9):
            print("  Slot must be a number 0-9 (0-4 = Team A slots 1-5, 5-9 = Team B slots 1-5).")
            continue

        slot_num = int(slot_token)
        heroes, label, slot_index = team_context(slot_num)
        hero_query = parts[1] if len(parts) == 2 else None

        if hero_query is None or hero_query.lower() in ("clear", "none", "-", "remove"):
            if heroes[slot_index] is None:
                print(f"  Slot {slot_num} ({label}) is already empty.")
            else:
                cleared = hero_id_to_name.get(heroes[slot_index], f"hero_{heroes[slot_index]}")
                heroes[slot_index] = None
                print(f"  Cleared slot {slot_num} ({label}, was {cleared}).")
                refresh()
            continue

        lookup = resolve_hero(hero_query, hero_id_to_name)
        if lookup.confidence == "ambiguous":
            print(f"  {hero_query!r} matches multiple heroes: {', '.join(lookup.candidates)}. Type more letters.")
            continue
        if lookup.hero_id is None:
            print(f"  Could not resolve hero {hero_query!r}.")
            continue
        if lookup.confidence in ("prefix", "fuzzy"):
            print(f"  (matched to {lookup.matched_name})")

        # A hero can only be on the field once -- if it's already assigned
        # elsewhere, move it here instead of rejecting the pick.
        for team_offset, (other_heroes, other_label) in enumerate(
            ((team_a_heroes, team_a_label), (team_b_heroes, team_b_label))
        ):
            for i, h in enumerate(other_heroes):
                if other_heroes is heroes and i == slot_index:
                    continue
                if h == lookup.hero_id:
                    other_heroes[i] = None
                    print(f"  Moved {lookup.matched_name} from slot {team_offset * 5 + i} ({other_label}).")

        heroes[slot_index] = lookup.hero_id
        refresh()


if __name__ == "__main__":
    main()
