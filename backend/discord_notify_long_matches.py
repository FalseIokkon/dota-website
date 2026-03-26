#!/usr/bin/env python3
"""
discord_notify_long_matches.py

Purpose:
Scan pro_matches in dota.db for long pro matches in selected tournaments and
send Discord webhook notifications for matches that have not already been
notified.
"""

import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests

from config import BACKEND_DIR, DATA_DIR, DISCORD_WEBHOOK_URL
from db import (
    connect_db,
    create_tables,
    get_unnotified_long_pro_matches,
    mark_long_match_notified,
)

BACKEND_PATH = Path(BACKEND_DIR)
DATA_PATH = Path(DATA_DIR)

DB_PATH = DATA_PATH / "dota.db"
LOG_PATH = BACKEND_PATH / "discord_notify_long_matches.txt"
TOURNAMENT_LIST_PATH = BACKEND_PATH / "tournament_list.txt"

LONG_SECONDS = 3600
MAX_NOTIFICATIONS_PER_RUN = 50


def log_line(message: str) -> None:
    """
    Append one timestamped line to the Discord notifier log file.

    Args:
        message: Text to write to the log.
    """
    BACKEND_PATH.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(f"{datetime.now()}\t{message}\n")


def load_tournament_set() -> set[str]:
    """
    Load the allowed tournament names from tournament_list.txt.

    Returns:
        A set of stripped non-empty tournament names.
    """
    names: set[str] = set()

    try:
        with open(TOURNAMENT_LIST_PATH, "r", encoding="utf-8") as file:
            for line in file:
                name = line.strip()
                if name:
                    names.add(name)
    except FileNotFoundError:
        log_line(f"ERROR: missing {TOURNAMENT_LIST_PATH}")

    return names


def send_discord(content: str) -> bool:
    """
    Send a message to the configured Discord webhook.

    Args:
        content: Message body to send.

    Returns:
        True if the webhook call succeeded, else False.
    """
    if not DISCORD_WEBHOOK_URL:
        log_line(f"WARN: DISCORD_WEBHOOK_URL not set; would send: {content}")
        return False

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json={"content": content},
            timeout=15,
        )
        if 200 <= response.status_code < 300:
            return True

        log_line(
            f"ERROR: Discord webhook HTTP {response.status_code}: "
            f"{response.text[:200]}"
        )
        return False

    except requests.RequestException as exc:
        log_line(f"ERROR: Discord webhook failed: {exc}")
        return False


def format_masked_duration(duration_seconds: int) -> str:
    """
    Convert a duration in seconds into a masked display string like 6x:xx.

    Args:
        duration_seconds: Match duration in seconds.

    Returns:
        Masked duration string.
    """
    minutes = duration_seconds // 60
    if minutes < 100:
        return f"{str(minutes)[0]}x:xx"
    return f"{str(minutes)[0]}xx:xx"


def format_match_datetime(start_time: int | None) -> str:
    """
    Convert epoch start time into a readable local datetime string.

    Args:
        start_time: Epoch seconds or None.

    Returns:
        Human-readable datetime string.
    """
    if not start_time:
        return "Unknown start time"

    local_dt = datetime.fromtimestamp(start_time)
    return local_dt.astimezone().strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")


def build_message(match: dict) -> str:
    """
    Build the Discord message body for a long match notification.

    Args:
        match: Dictionary containing match summary fields.

    Returns:
        Formatted Discord message string.
    """
    match_id = match["match_id"]
    radiant = match.get("radiant_name") or "Radiant"
    dire = match.get("dire_name") or "Dire"
    duration = int(match.get("duration") or 0)
    league = match.get("league_name") or "Unknown League"
    match_datetime = format_match_datetime(match.get("start_time"))
    masked_duration = format_masked_duration(duration)

    search_query = f"{league} {radiant} vs {dire}"
    encoded_query = quote_plus(search_query)
    youtube_url = f"https://www.youtube.com/results?search_query={encoded_query}"

    return (
        f"**Long Match Detected**\n"
        f"**{radiant} vs {dire}**\n"
        f"Date/Time: `{match_datetime}`\n"
        f"Duration: `{masked_duration}`\n"
        f"League: {league}\n"
        f"\n"
        f"🔎 [Dotabuff](https://www.dotabuff.com/matches/{match_id})\n"
        f"▶️ [YouTube Search](<{youtube_url}>)\n"
        f"Match ID: `{match_id}`"
    )


def main() -> None:
    """
    Find unnotified long pro matches in selected tournaments and notify Discord once per match.

    Steps:
    1. Load tournament names.
    2. Query pro_matches in dota.db for long matches not yet notified.
    3. Send Discord messages.
    4. Mark successfully sent matches as notified in the database.
    5. Log a summary.
    """
    log_line("START discord_notify_long_matches")

    tournament_names = load_tournament_set()
    if not tournament_names:
        log_line("No tournament names loaded; exiting.")
        return

    DATA_PATH.mkdir(parents=True, exist_ok=True)
    conn = connect_db(str(DB_PATH))
    create_tables(conn)

    try:
        matches = get_unnotified_long_pro_matches(
            conn=conn,
            tournament_names=tournament_names,
            long_seconds=LONG_SECONDS,
            limit=MAX_NOTIFICATIONS_PER_RUN,
        )

        if not matches:
            log_line("Found 0 unnotified long matches; sent 0 new notifications.")
            return

        sent_count = 0
        failed_count = 0

        for match in matches:
            match_id = match["match_id"]
            message = build_message(match)
            ok = send_discord(message)

            if ok:
                mark_long_match_notified(conn, match_id)
                sent_count += 1

                masked_duration = format_masked_duration(int(match.get("duration") or 0))
                radiant = match.get("radiant_name") or "Radiant"
                dire = match.get("dire_name") or "Dire"
                league = match.get("league_name") or "Unknown League"

                log_line(
                    f"NOTIFIED long match {match_id} "
                    f"({masked_duration}) {radiant} vs {dire} [{league}]"
                )
                time.sleep(0.5)
            else:
                failed_count += 1

        log_line(
            f"Found {len(matches)} unnotified long matches; "
            f"sent {sent_count} new notifications; failed {failed_count}."
        )

    finally:
        conn.close()
        log_line("END discord_notify_long_matches")


if __name__ == "__main__":
    main()