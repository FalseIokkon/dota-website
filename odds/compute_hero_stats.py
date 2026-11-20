#!/usr/bin/env python3
"""
compute_hero_stats.py

Purpose:
Inspection CLI for the hero-tracking data: prints the current-patch hero
leaderboard (win rate / pick rate) and saves both hero_meta and
hero_affinity tables to data/derived/ for manual sanity-checking. Not
required by find_ev_bets.py or live_draft.py -- they import the underlying
functions directly (same "recompute fresh each run" convention as
compute_ratings.py) -- this script exists purely so the numbers can be
eyeballed before trusting them live.

Location:
    odds/compute_hero_stats.py
"""

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DB_PATH  # noqa: E402
from odds.hero_affinity import compute_hero_affinity  # noqa: E402
from odds.hero_meta import compute_hero_meta, current_patch  # noqa: E402
from odds.hero_names import load_hero_names  # noqa: E402

HERO_META_OUTPUT = REPO_ROOT / "data" / "derived" / "hero_meta.csv"
HERO_AFFINITY_OUTPUT = REPO_ROOT / "data" / "derived" / "hero_affinity.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print/save current-patch hero meta and player-hero affinity stats.")
    parser.add_argument("--top", type=int, default=20, help="How many heroes to print in the meta leaderboard (default 20).")
    parser.add_argument("--min-games", type=int, default=20, help="Hide heroes with fewer current-patch games than this (default 20).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    patch = current_patch(str(DB_PATH))
    print(f"Current patch: {patch}")

    names = load_hero_names()

    meta = compute_hero_meta(str(DB_PATH))
    meta_rows = [
        {
            "hero_id": m.hero_id,
            "name": names.get(m.hero_id, f"hero_{m.hero_id}"),
            "games": m.games,
            "pick_rate": round(m.pick_rate, 4),
            "win_rate_raw": round(m.win_rate_raw, 4),
            "win_rate_shrunk": round(m.win_rate_shrunk, 4),
            "ban_count": m.ban_count,
            "ban_rate": round(m.ban_rate, 4),
            "presence_rate": round(m.presence_rate, 4),
        }
        for m in meta.values()
    ]
    fieldnames = ["hero_id", "name", "games", "pick_rate", "win_rate_raw", "win_rate_shrunk",
                  "ban_count", "ban_rate", "presence_rate"]

    HERO_META_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with HERO_META_OUTPUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(meta_rows, key=lambda r: r["win_rate_shrunk"], reverse=True))
    print(f"Wrote {len(meta_rows)} heroes to {HERO_META_OUTPUT}")

    shown = sorted(
        [r for r in meta_rows if r["games"] >= args.min_games],
        key=lambda r: r["win_rate_shrunk"], reverse=True,
    )
    print(f"\n{'Hero':22s} {'Games':>6s} {'PickRate':>9s} {'WR raw':>7s} {'WR shrunk':>9s} {'BanRate':>8s}")
    for r in shown[: args.top]:
        print(f"{r['name'][:22]:22s} {r['games']:6d} {r['pick_rate']*100:8.1f}% {r['win_rate_raw']*100:6.1f}% "
              f"{r['win_rate_shrunk']*100:8.1f}% {r['ban_rate']*100:7.1f}%")

    # Sorted by ban_rate independently of the pick-count filter above --
    # a hero banned constantly but rarely allowed to be *picked* would
    # otherwise be invisible from the win-rate table (this is exactly the
    # "banned so much we barely have pick data on it" case that matters
    # for hero_adjustment.py's ban-pressure term).
    most_banned = sorted(meta_rows, key=lambda r: r["ban_rate"], reverse=True)
    most_banned = [r for r in most_banned if r["ban_rate"] > 0][: args.top]
    if most_banned:
        print(f"\nMost-banned heroes this patch (independent of how often they're actually picked):")
        print(f"{'Hero':22s} {'BanRate':>8s} {'Games picked':>13s} {'WR shrunk':>9s}")
        for r in most_banned:
            print(f"{r['name'][:22]:22s} {r['ban_rate']*100:7.1f}% {r['games']:13d} {r['win_rate_shrunk']*100:8.1f}%")

    affinity = compute_hero_affinity(str(DB_PATH))
    affinity_rows = [
        {
            "account_id": stat.account_id,
            "hero_id": stat.hero_id,
            "hero_name": names.get(stat.hero_id, f"hero_{stat.hero_id}"),
            "games": stat.games,
            "win_rate": round(stat.win_rate, 4),
            "affinity_delta": round(stat.affinity_delta, 4),
        }
        for stat in affinity.values()
    ]
    affinity_rows.sort(key=lambda r: r["games"], reverse=True)

    with HERO_AFFINITY_OUTPUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["account_id", "hero_id", "hero_name", "games", "win_rate", "affinity_delta"])
        writer.writeheader()
        writer.writerows(affinity_rows)
    print(f"\nWrote {len(affinity_rows)} (player, hero) pairs to {HERO_AFFINITY_OUTPUT}")


if __name__ == "__main__":
    main()
