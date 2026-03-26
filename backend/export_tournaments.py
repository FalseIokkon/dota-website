#!/usr/bin/env python3
import sqlite3
from pathlib import Path

# --- Paths ---
PROJECT_ROOT = Path("/home/tankionlinefirstseargent/projects/dota-website")
DB_PATH = PROJECT_ROOT / "backend" / "data" / "dota.db"
OUTPUT_PATH = PROJECT_ROOT / "backend" / "tournaments.txt"


def main():
    if not DB_PATH.exists():
        print(f"❌ Database not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                league_name,
                MAX(start_time) AS last_seen
            FROM pro_matches
            WHERE league_name IS NOT NULL
              AND TRIM(league_name) != ''
            GROUP BY league_name
            ORDER BY last_seen ASC;
        """)

        tournaments = [row["league_name"].strip() for row in cursor.fetchall()]

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            for name in tournaments:
                f.write(name + "\n")

        print(f"✅ Exported {len(tournaments)} tournaments (sorted by recency) → {OUTPUT_PATH}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()