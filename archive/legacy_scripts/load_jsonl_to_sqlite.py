#!/usr/bin/env python3
import sys, json, sqlite3, pathlib

def to_int_bool(val):
    if isinstance(val, bool): return 1 if val else 0
    if val in (0, 1): return int(val)
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true","1","yes","y"): return 1
        if v in ("false","0","no","n"): return 0
    return None

def main(path_jsonl, path_db):
    src = pathlib.Path(path_jsonl)
    if not src.exists():
        print(f"ERROR: {src} not found")
        sys.exit(1)

    conn = sqlite3.connect(path_db)
    try:
        # Speed + safety
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

        upsert_sql = """
        INSERT INTO pro_matches (
          match_id, duration, start_time,
          radiant_team_id, radiant_name,
          dire_team_id, dire_name,
          leagueid, league_name,
          series_id, series_type,
          radiant_score, dire_score,
          radiant_win, version
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(match_id) DO UPDATE SET
          duration=excluded.duration,
          start_time=excluded.start_time,
          radiant_team_id=excluded.radiant_team_id,
          radiant_name=excluded.radiant_name,
          dire_team_id=excluded.dire_team_id,
          dire_name=excluded.dire_name,
          leagueid=excluded.leagueid,
          league_name=excluded.league_name,
          series_id=excluded.series_id,
          series_type=excluded.series_type,
          radiant_score=excluded.radiant_score,
          dire_score=excluded.dire_score,
          radiant_win=excluded.radiant_win,
          version=excluded.version;
        """

        rows = []
        with src.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"Skipping malformed JSON at line {line_no}: {e}")
                    continue

                rows.append((
                    obj.get("match_id"),
                    obj.get("duration"),
                    obj.get("start_time"),
                    obj.get("radiant_team_id"),
                    obj.get("radiant_name"),
                    obj.get("dire_team_id"),
                    obj.get("dire_name"),
                    obj.get("leagueid"),
                    obj.get("league_name"),
                    obj.get("series_id"),
                    obj.get("series_type"),
                    obj.get("radiant_score"),
                    obj.get("dire_score"),
                    to_int_bool(obj.get("radiant_win")),
                    obj.get("version"),
                ))

        with conn:
            conn.executemany(upsert_sql, rows)

        print(f"Imported/updated {len(rows)} rows into {path_db}:pro_matches")
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python load_jsonl_to_sqlite.py 2025.jsonl dota.db")
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
