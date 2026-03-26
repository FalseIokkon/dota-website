"""
fetch_match_details.py

Purpose:
Fetch full OpenDota match details for match IDs already known in match_index
but not yet stored in matches, then store selected fields and the full raw
payload in the matches table.
"""

import json
from datetime import datetime
from pathlib import Path

from config import OPENDOTA_API_KEY, DATA_DIR, BACKEND_DIR
from db import (
    connect_db,
    create_tables,
    get_missing_match_detail_ids,
    upsert_match_detail,
    increment_api_usage,
    get_api_usage,
    match_detail_exists,
)
from opendota_client import OpenDotaClient

BACKEND_PATH = Path(BACKEND_DIR)
DATA_PATH = Path(DATA_DIR)

LOG_PATH = BACKEND_PATH / "fetch_match_details_log.txt"
DB_PATH = DATA_PATH / "dota.db"

MAX_MATCH_DETAILS_PER_RUN = 25


def log_line(message: str) -> None:
    """
    Append one timestamped line to the fetch_match_details log file.

    Args:
        message: Text to write to the log.
    """
    BACKEND_PATH.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(f"{datetime.now()}\t{message}\n")


def main() -> None:
    """
    Fetch and store full match detail payloads for missing matches.

    Steps:
    1. Connect to SQLite and ensure tables exist.
    2. Find newest match IDs present in match_index but missing from matches.
    3. Fetch up to MAX_MATCH_DETAILS_PER_RUN full match payloads.
    4. Store selected columns plus the full JSON payload in matches.
    5. Track successful API usage in api_usage.
    6. Log the result in a format similar to fetch_pro_matches.py.
    """
    log_line("START fetch_match_details")
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
        match_ids = get_missing_match_detail_ids(
            conn,
            limit=MAX_MATCH_DETAILS_PER_RUN,
        )

        if not match_ids:
            monthly_calls = get_api_usage(conn, provider="opendota")
            log_line(
                f"Fetched 0 match details; new 0; existing 0; failed 0; "
                f"month_api_calls {monthly_calls}."
            )
            return

        new_count = 0
        existing_count = 0
        failed_count = 0

        for match_id in match_ids:
            try:
                if match_detail_exists(conn, match_id):
                    existing_count += 1
                    continue

                detail = client.get_match(match_id)

                if not detail or not isinstance(detail, dict):
                    failed_count += 1
                    continue

                payload_json = json.dumps(detail, separators=(",", ":"), ensure_ascii=False)
                upsert_match_detail(conn, detail, payload_json)
                new_count += 1

            except Exception as exc:
                failed_count += 1
                log_line(f"ERROR: match_id={match_id} detail fetch/store failed: {exc}")

        monthly_calls = get_api_usage(conn, provider="opendota")

        log_line(
            f"Fetched {len(match_ids)} match details; "
            f"new {new_count}; existing {existing_count}; failed {failed_count}; "
            f"month_api_calls {monthly_calls}."
        )

    except Exception as exc:
        log_line(f"ERROR: {exc}")
        raise
    finally:
        client.close()
        conn.close()

    log_line("END fetch_match_details")


if __name__ == "__main__":
    main()