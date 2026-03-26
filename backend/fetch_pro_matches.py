"""
fetch_pro_matches.py

Purpose:
Fetch recent pro matches from OpenDota, add their match IDs into match_index,
and store lightweight pro-match metadata in pro_matches without fetching full
match detail payloads.
"""

from datetime import datetime
from pathlib import Path

from config import OPENDOTA_API_KEY, DATA_DIR, BACKEND_DIR
from db import (
    connect_db,
    create_tables,
    insert_many_match_index,
    upsert_pro_match,
    pro_match_exists,
    increment_api_usage,
    get_api_usage,
)
from opendota_client import OpenDotaClient

BACKEND_PATH = Path(BACKEND_DIR)
DATA_PATH = Path(DATA_DIR)

LOG_PATH = BACKEND_PATH / "fetch_pro_matches_log.txt"
DB_PATH = DATA_PATH / "dota.db"


def log_line(message: str) -> None:
    """
    Append one timestamped line to the fetch_pro_matches log file.

    Args:
        message: Text to write to the log.
    """
    BACKEND_PATH.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(f"{datetime.now()}\t{message}\n")


def main() -> None:
    """
    Fetch the latest page of pro matches and store only new rows in the database.

    Steps:
    1. Connect to SQLite and ensure tables exist.
    2. Fetch recent pro matches from OpenDota.
    3. Insert all returned match IDs into match_index.
    4. Insert only match rows not already present in pro_matches.
    5. Track successful API calls in api_usage.
    6. Log how many were fetched, new, existing, skipped, and monthly API total.

    This script does not fetch /matches/{match_id} details.
    """
    log_line("START fetch_pro_matches")
    DATA_PATH.mkdir(parents=True, exist_ok=True)

    api_key = OPENDOTA_API_KEY
    if not api_key:
        log_line("CONFIG ERROR: OPENDOTA_API_KEY is not set")
        raise RuntimeError("OPENDOTA_API_KEY is not set")

    conn = connect_db(str(DB_PATH))
    create_tables(conn)

    def record_api_call() -> None:
        """
        Increment the persisted OpenDota API usage counter for the current billing period.
        """
        increment_api_usage(conn, provider="opendota", count=1)

    client = OpenDotaClient(
        api_key=api_key,
        timeout=30,
        user_agent="dota-website-bot/1.0",
        sleep_seconds=0.0,
        on_successful_request=record_api_call,
    )

    try:
        pro_matches = client.get_pro_matches()

        if not pro_matches:
            monthly_calls = get_api_usage(conn, provider="opendota")
            log_line(f"No pro matches returned from API. month_api_calls {monthly_calls}.")
            return

        # Ensure every valid returned match_id exists in match_index.
        match_ids = [
            match["match_id"]
            for match in pro_matches
            if isinstance(match, dict) and match.get("match_id") is not None
        ]
        insert_many_match_index(conn, match_ids)

        new_count = 0
        existing_count = 0
        skipped_count = 0

        for match in pro_matches:
            if not isinstance(match, dict):
                skipped_count += 1
                continue

            match_id = match.get("match_id")
            if match_id is None:
                skipped_count += 1
                continue

            if pro_match_exists(conn, match_id):
                existing_count += 1
                continue

            upsert_pro_match(conn, match)
            new_count += 1

        monthly_calls = get_api_usage(conn, provider="opendota")

        log_line(
            f"Fetched {len(pro_matches)} pro matches; "
            f"new {new_count}; existing {existing_count}; skipped {skipped_count}; "
            f"month_api_calls {monthly_calls}."
        )

    except Exception as exc:
        log_line(f"ERROR: {exc}")
        raise
    finally:
        client.close()
        conn.close()

    log_line("END fetch_pro_matches")


if __name__ == "__main__":
    main()