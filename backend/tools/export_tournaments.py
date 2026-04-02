#!/usr/bin/env python3
"""
export_tournaments.py

Location:
    backend/tools/export_tournaments.py

Purpose:
    Extract all unique tournament (league) names from the database
    and save them to a text file for later use.
"""

import sqlite3
import sys
from pathlib import Path

# Make backend/ importable
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT))

from app.config import DB_PATH, PROJECT_ROOT  # noqa: E402

# Output file (you can move this later if desired)
OUTPUT_PATH = PROJECT_ROOT / "backend" / "tools" / "all_tournaments.txt"


def main():
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}")
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

        tournaments = [
            row["league_name"].strip()
            for row in cursor.fetchall()
            if row["league_name"]
        ]

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            for name in tournaments:
                f.write(name + "\n")

        print(f"[OK] Exported {len(tournaments)} tournaments → {OUTPUT_PATH}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()