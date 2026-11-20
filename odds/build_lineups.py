#!/usr/bin/env python3
"""
build_lineups.py

Purpose:
One-time/incremental ETL: pull the 10 (account_id, personaname, hero_id,
is_radiant) player rows AND the draft's picks/bans out of each match's
cached payload_json in `matches`, writing them to two small CSV caches
(data/derived/lineups.csv and data/derived/picks_bans.csv).

Why this exists:
`matches.payload_json` blobs are ~20KB+ each and the table is ~10GB, so a
full scan takes minutes (measured: ~3.7ms/row, ~3 min for all matches) --
too slow to run as a live dependency of the rating pipeline. This script
pays that cost once, for both caches in the same pass (adding picks_bans.csv
later reused this scan rather than paying for a second one). Reruns only
scan match_ids newer than what's already cached (match_id is monotonic with
time in OpenDota, same assumption scraper/fetch_pro_matches.py relies on
for pagination) -- each cache tracks its own progress independently, so
adding a new cache to this script only re-pays the scan cost once, for
whichever match_ids that new cache hasn't seen yet.

Location:
    odds/build_lineups.py
"""

import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from core.config import DB_PATH  # noqa: E402

LINEUPS_PATH = REPO_ROOT / "data" / "derived" / "lineups.csv"
LINEUPS_FIELDNAMES = ["match_id", "account_id", "personaname", "hero_id", "is_radiant"]

PICKS_BANS_PATH = REPO_ROOT / "data" / "derived" / "picks_bans.csv"
PICKS_BANS_FIELDNAMES = ["match_id", "hero_id", "is_pick", "is_radiant", "order"]

BATCH_SIZE = 500
PROGRESS_EVERY = 2000


def max_extracted_match_id(path: Path) -> int:
    """Highest match_id already present in a CSV cache, or 0 if none."""
    if not path.exists():
        return 0
    max_id = 0
    with path.open() as f:
        for row in csv.DictReader(f):
            max_id = max(max_id, int(row["match_id"]))
    return max_id


def main() -> None:
    lineups_since = max_extracted_match_id(LINEUPS_PATH)
    picks_bans_since = max_extracted_match_id(PICKS_BANS_PATH)
    since = min(lineups_since, picks_bans_since)
    print(f"lineups.csv resuming after match_id={lineups_since}, picks_bans.csv after "
          f"match_id={picks_bans_since} (0 means starting fresh); scanning from {since}.")

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT match_id, payload_json FROM matches WHERE match_id > ? ORDER BY match_id", (since,))

    LINEUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lineups_is_new = not LINEUPS_PATH.exists()
    picks_bans_is_new = not PICKS_BANS_PATH.exists()

    scanned = 0
    lineups_written = 0
    picks_bans_written = 0
    t0 = time.time()

    with LINEUPS_PATH.open("a", newline="") as lf, PICKS_BANS_PATH.open("a", newline="") as pf:
        lineups_writer = csv.DictWriter(lf, fieldnames=LINEUPS_FIELDNAMES)
        if lineups_is_new:
            lineups_writer.writeheader()
        picks_bans_writer = csv.DictWriter(pf, fieldnames=PICKS_BANS_FIELDNAMES)
        if picks_bans_is_new:
            picks_bans_writer.writeheader()

        while True:
            batch = cur.fetchmany(BATCH_SIZE)
            if not batch:
                break

            for match_id, payload in batch:
                scanned += 1
                try:
                    data = json.loads(payload) if payload else {}
                except json.JSONDecodeError:
                    continue

                if match_id > lineups_since:
                    players = data.get("players") or []
                    for i, p in enumerate(players):
                        account_id = p.get("account_id") or f"anon_{match_id}_{i}"
                        lineups_writer.writerow({
                            "match_id": match_id,
                            "account_id": account_id,
                            "personaname": p.get("personaname") or "",
                            "hero_id": p.get("hero_id"),
                            "is_radiant": int(bool(p.get("isRadiant"))),
                        })
                        lineups_written += 1

                if match_id > picks_bans_since:
                    # team=0/1 in picks_bans is radiant/dire -- confirmed by
                    # cross-checking against players[].isRadiant for a known
                    # match, not assumed from OpenDota's (undocumented here)
                    # convention.
                    for entry in data.get("picks_bans") or []:
                        picks_bans_writer.writerow({
                            "match_id": match_id,
                            "hero_id": entry.get("hero_id"),
                            "is_pick": int(bool(entry.get("is_pick"))),
                            "is_radiant": int(entry.get("team") == 0),
                            "order": entry.get("order"),
                        })
                        picks_bans_written += 1

            lf.flush()
            pf.flush()
            if scanned % PROGRESS_EVERY < BATCH_SIZE:
                elapsed = time.time() - t0
                rate = scanned / elapsed if elapsed > 0 else 0
                print(f"  scanned {scanned} matches, wrote {lineups_written} lineup rows / "
                      f"{picks_bans_written} pick-ban rows ({elapsed:.0f}s, {rate:.0f} matches/s)")

    conn.close()
    elapsed = time.time() - t0
    print(f"Done in {elapsed:.0f}s. Scanned {scanned} matches, wrote {lineups_written} lineup rows to "
          f"{LINEUPS_PATH} and {picks_bans_written} pick-ban rows to {PICKS_BANS_PATH}.")


if __name__ == "__main__":
    main()
