#!/usr/bin/env python3
"""
compute_ratings.py

Purpose:
Run the Glicko-2 pipeline over the full match history in dota.db and print/
save a team leaderboard. Rerunnable any time new results land in the DB.

Location:
    odds/compute_ratings.py
"""

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DB_PATH  # noqa: E402
from odds.player_names import display_name, load_player_names  # noqa: E402
from odds.player_ratings import build_current_player_ratings, composite_rating  # noqa: E402
from odds.ratings import build_current_ratings  # noqa: E402
from odds.ti2026_teams import TI2026_TEAMS, all_team_ids_for, apply_lineup_overrides, resolve_team_id  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "data" / "derived" / "team_ratings.csv"
OUTPUT_PATH_BY_PLAYER = REPO_ROOT / "data" / "derived" / "team_ratings_by_player.csv"

# How many RD to discount the point-estimate rating by for the
# "conservative" leaderboard column (same idea as a TrueSkill-style
# conservative rating: penalize teams we're still uncertain about).
CONSERVATIVE_Z = 2.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute current Glicko-2 team ratings.")
    parser.add_argument("--top", type=int, default=30, help="How many teams to print (default 30).")
    parser.add_argument(
        "--ti2026",
        action="store_true",
        help="Filter output to the TI2026_TEAMS list in odds/ti2026_teams.py instead of the full leaderboard.",
    )
    parser.add_argument("--min-games", type=int, default=1, help="Hide teams with fewer games than this.")
    parser.add_argument(
        "--by-player",
        action="store_true",
        help=(
            "Rate each team by the composite of its current lineup's individual player "
            "ratings instead of the org's own win/loss history. Reflects roster changes "
            "(transfers, rebrands) immediately; see odds/player_ratings.py."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    result = build_current_ratings(str(DB_PATH))
    player_result = build_current_player_ratings(str(DB_PATH)) if args.by_player else None
    curated_names = load_player_names() if args.by_player else {}

    games_played: dict[int, int] = {}
    for p in result.predictions:
        games_played[p.team_a] = games_played.get(p.team_a, 0) + 1
        games_played[p.team_b] = games_played.get(p.team_b, 0) + 1

    team_ids = list(result.states.keys())
    ti2026_name_by_team_id: dict[int, str] = {}

    if args.ti2026:
        if not TI2026_TEAMS:
            print("[WARN] TI2026_TEAMS is empty (odds/ti2026_teams.py) -- showing full leaderboard instead.")
        else:
            resolved = []
            for name in TI2026_TEAMS:
                lookup = resolve_team_id(name, result.names)
                if lookup.team_id is None:
                    if lookup.confidence == "ambiguous":
                        print(f"[WARN] {name!r} matches multiple teams: {', '.join(lookup.candidates)}.")
                    else:
                        print(f"[WARN] Could not resolve TI2026 team name to DB team_id: {name!r}")
                    continue
                if lookup.confidence in ("alias", "prefix", "fuzzy", "override"):
                    print(f"[INFO] {lookup.confidence}-matched {name!r} -> {lookup.matched_name!r} (team_id={lookup.team_id})")
                resolved.append(lookup.team_id)
                ti2026_name_by_team_id[lookup.team_id] = name
            team_ids = resolved

    rows = []
    for team_id in team_ids:
        if player_result is not None:
            lineup_ids = player_result.current_lineup_by_team.get(team_id)
            if not lineup_ids:
                print(f"[WARN] No cached lineup for {result.names.get(team_id, team_id)!r} (team_id={team_id}) -- skipping.")
                continue

            ti2026_name = ti2026_name_by_team_id.get(team_id)
            if ti2026_name:
                patched_ids = apply_lineup_overrides(ti2026_name, lineup_ids)
                if patched_ids != lineup_ids:
                    print(f"[INFO] Applied manual lineup override for {ti2026_name!r}")
                lineup_ids = patched_ids

            rating = composite_rating([player_result.effective_rating(a) for a in lineup_ids])
            lineup = ", ".join(display_name(a, curated_names, player_result.names) for a in lineup_ids)
        else:
            rating = result.effective_rating(team_id)
            lineup = ""

        # Several TI2026 rosters have their games split across more than
        # one pro_matches team_id (orgs renaming to dodge a tournament's
        # no-gambling-sponsor rules get a fresh team_id per name from
        # OpenDota) -- sum activity across all known fragments so "games"
        # reflects true total experience. Only done in --by-player mode:
        # there the rating itself is already correctly built from every
        # fragment (it's per-account_id, not per-team_id), so the merged
        # count matches what the rating actually reflects. In org-level
        # mode the rating is still only that one team_id's history, so
        # showing a merged count there would make "games" inconsistent
        # with what the displayed rating was actually computed from.
        ti2026_name = ti2026_name_by_team_id.get(team_id)
        if ti2026_name and player_result is not None:
            games = sum(games_played.get(tid, 0) for tid in all_team_ids_for(ti2026_name, team_id))
        else:
            games = games_played.get(team_id, 0)

        rows.append({
            "team_id": team_id,
            "name": result.names.get(team_id, f"team_{team_id}"),
            "rating": round(rating.value, 1),
            "rd": round(rating.rd, 1),
            "conservative_rating": round(rating.value - CONSERVATIVE_Z * rating.rd, 1),
            "sigma": round(rating.sigma, 4),
            "games": games,
            "lineup": lineup,
        })

    rows = [r for r in rows if r["games"] >= args.min_games]
    rows.sort(key=lambda r: r["rating"], reverse=True)

    output_path = OUTPUT_PATH_BY_PLAYER if player_result is not None else OUTPUT_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["team_id", "name", "rating", "rd", "conservative_rating", "sigma", "games", "lineup"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} teams to {output_path}")

    if player_result is not None:
        header = f"{'Name':22s} {'Rating':>8s} {'RD':>7s} {'Conserv.':>9s} {'Games':>6s}  Current Lineup"
    else:
        header = f"{'Name':30s} {'Rating':>8s} {'RD':>7s} {'Conserv.':>9s} {'Games':>6s}"
    print(header)
    print("-" * len(header))
    for r in rows[: args.top]:
        if player_result is not None:
            print(f"{r['name'][:22]:22s} {r['rating']:8.1f} {r['rd']:7.1f} {r['conservative_rating']:9.1f} {r['games']:6d}  {r['lineup']}")
        else:
            print(f"{r['name'][:30]:30s} {r['rating']:8.1f} {r['rd']:7.1f} {r['conservative_rating']:9.1f} {r['games']:6d}")


if __name__ == "__main__":
    main()
