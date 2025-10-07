import json
import requests
import os
from datetime import datetime
import sqlite3
from pathlib import Path

# The purpose of this file is to run hourly, scan for new games, and add any new games to dota.db AND data/{year}.jsonl

year = datetime.now().year
log_path = "/home/tankionlinefirstseargent/projects/dota-website/backend/log.txt"
data_dir = "/home/tankionlinefirstseargent/projects/dota-website/backend/data"
dota_db_path = f"{data_dir}/dota.db"
jsonl_path = f"{data_dir}/{year}.jsonl"

Path(data_dir).mkdir(parents=True, exist_ok=True)

# Step 1: Build set of existing IDs from {year}.jsonl (skip bad lines)
existing_ids = set()
if os.path.exists(jsonl_path):
    with open(jsonl_path, "r") as f:
        for line in f:
            try:
                match = json.loads(line)
                mid = match.get("match_id")
                if mid is not None:
                    existing_ids.add(mid)
            except json.JSONDecodeError:
                continue

# API Call
url = "https://api.opendota.com/api/proMatches"
try:
    response = requests.get(url, timeout=20)
    status_ok = (response.status_code == 200)
except requests.RequestException as e:
    status_ok = False
    with open(log_path, "a") as log:
        log.write(f"{datetime.now()}\tFAILED request: {e}\n")

if status_ok:
    new_matches = response.json() or []
    unique_new_matches = [m for m in new_matches if m.get("match_id") not in existing_ids]
    unique_new_matches.sort(key=lambda x: x.get("match_id", 0))

    if unique_new_matches:
        # Prepare rows to insert
        rows = []
        for m in unique_new_matches:
            rows.append((
                m.get("match_id"),
                m.get("duration"),
                m.get("start_time"),
                m.get("radiant_team_id"),
                m.get("radiant_name"),
                m.get("dire_team_id"),
                m.get("dire_name"),
                m.get("leagueid"),
                m.get("league_name"),
                m.get("series_id"),
                m.get("series_type"),
                m.get("radiant_score"),
                m.get("dire_score"),
                1 if m.get("radiant_win") else 0,
                m.get("version"),
            ))

        # Insert in one transaction
        try:
            conn = sqlite3.connect(dota_db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")

            insert_sql = """
            INSERT OR IGNORE INTO pro_matches (
                match_id, duration, start_time,
                radiant_team_id, radiant_name,
                dire_team_id, dire_name,
                leagueid, league_name,
                series_id, series_type,
                radiant_score, dire_score,
                radiant_win, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """

            with conn:  # atomic transaction
                conn.executemany(insert_sql, rows)

            conn.close()

            # Only after DB commit: append to JSONL to keep them consistent
            with open(jsonl_path, "a") as f:
                for m in unique_new_matches:
                    f.write(json.dumps(m) + "\n")

            with open(log_path, "a") as log:
                log.write(f"{datetime.now()}\tAdded {len(unique_new_matches)} new matches to jsonl & dota.db.\n")

        except sqlite3.Error as e:
            # If DB insert fails, do NOT write to JSONL; log the error
            with open(log_path, "a") as log:
                log.write(f"{datetime.now()}\tDB ERROR: {e}\n")

    else:
        with open(log_path, "a") as log:
            log.write(f"{datetime.now()}\tNo New Matches Added.\n")
else:
    with open(log_path, "a") as log:
        log.write(f"{datetime.now()}\tFAILED to Fetch Data: HTTP {response.status_code}\n")
