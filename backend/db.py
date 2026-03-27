"""
db.py

Purpose:
Provide a small SQLite helper layer for the Dota project so all scripts use the
same database connection settings, schema creation logic, and common queries.
"""

import sqlite3
from pathlib import Path
from typing import Iterable, Optional
from datetime import datetime

def connect_db(db_path: str) -> sqlite3.Connection:
    """
    Open a SQLite connection with project-friendly settings.

    This enables:
    - WAL mode for better concurrent read/write behavior
    - NORMAL synchronous mode for a reasonable durability/speed balance
    - foreign key enforcement
    - busy timeout to avoid 'database is locked' errors

    Args:
        db_path: Absolute or relative path to the SQLite database file.

    Returns:
        A configured sqlite3.Connection object.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        db_path,
        timeout=30,  # wait up to 30s for locks
    )

    conn.row_factory = sqlite3.Row

    # Concurrency + durability tuning
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    # Lock handling
    conn.execute("PRAGMA busy_timeout = 30000;")  # 30 seconds

    # Integrity
    conn.execute("PRAGMA foreign_keys=ON;")

    return conn

def create_tables(conn: sqlite3.Connection) -> None:
    """
    Create the core project tables if they do not already exist.

    Tables:
    - match_index: universal registry of known match IDs
    - matches: full /matches/{match_id} payload cache
    - pro_matches: metadata discovered from /proMatches
    - personal_matches: metadata for user-specific matches

    Args:
        conn: Open SQLite connection.
    """
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS match_index (
              match_id      INTEGER PRIMARY KEY,
              discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
              match_id         INTEGER PRIMARY KEY,
              start_time       INTEGER,
              duration         INTEGER,
              radiant_win      INTEGER,
              radiant_score    INTEGER,
              dire_score       INTEGER,
              leagueid         INTEGER,
              series_id        INTEGER,
              series_type      INTEGER,
              game_mode        INTEGER,
              lobby_type       INTEGER,
              patch            INTEGER,
              region           INTEGER,
              replay_url       TEXT,
              payload_json     TEXT NOT NULL,
              fetched_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (match_id) REFERENCES match_index(match_id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pro_matches (
              match_id        INTEGER PRIMARY KEY,
              duration        INTEGER,
              start_time      INTEGER,
              radiant_team_id INTEGER,
              radiant_name    TEXT,
              dire_team_id    INTEGER,
              dire_name       TEXT,
              leagueid        INTEGER,
              league_name     TEXT,
              series_id       INTEGER,
              series_type     INTEGER,
              radiant_score   INTEGER,
              dire_score      INTEGER,
              radiant_win     INTEGER,
              version         INTEGER,
              discovered_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (match_id) REFERENCES match_index(match_id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS personal_matches (
              match_id        INTEGER PRIMARY KEY,
              account_id      INTEGER NOT NULL,
              player_slot     INTEGER,
              hero_id         INTEGER,
              is_radiant      INTEGER,
              discovered_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              source          TEXT,
              FOREIGN KEY (match_id) REFERENCES match_index(match_id) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_matches_fetched_at
            ON matches(fetched_at);
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pro_matches_start_time
            ON pro_matches(start_time);
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pro_matches_leagueid
            ON pro_matches(leagueid);
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pro_matches_series_id
            ON pro_matches(series_id);
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_personal_matches_account_id
            ON personal_matches(account_id);
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
              provider       TEXT NOT NULL,
              billing_period TEXT NOT NULL,
              call_count     INTEGER NOT NULL DEFAULT 0,
              updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (provider, billing_period)
            );
        """)

def insert_match_index(conn: sqlite3.Connection, match_id: int) -> None:
    """
    Insert a match ID into the universal registry if it is not already present.

    Args:
        conn: Open SQLite connection.
        match_id: The OpenDota match ID.
    """
    with conn:
        conn.execute("""
            INSERT OR IGNORE INTO match_index (match_id)
            VALUES (?);
        """, (match_id,))

def insert_many_match_index(conn: sqlite3.Connection, match_ids: Iterable[int]) -> None:
    """
    Insert multiple match IDs into the universal registry.

    Existing IDs are ignored.

    Args:
        conn: Open SQLite connection.
        match_ids: Iterable of OpenDota match IDs.
    """
    rows = [(match_id,) for match_id in match_ids]
    if not rows:
        return

    with conn:
        conn.executemany("""
            INSERT OR IGNORE INTO match_index (match_id)
            VALUES (?);
        """, rows)

def upsert_pro_match(conn: sqlite3.Connection, match: dict) -> None:
    """
    Insert or replace one pro match summary row.

    This stores the lightweight metadata returned by /proMatches.
    The caller should ensure the match ID already exists in match_index.

    Args:
        conn: Open SQLite connection.
        match: Dictionary returned by the OpenDota /proMatches endpoint.
    """
    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO pro_matches (
              match_id, duration, start_time,
              radiant_team_id, radiant_name,
              dire_team_id, dire_name,
              leagueid, league_name,
              series_id, series_type,
              radiant_score, dire_score,
              radiant_win, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            match.get("match_id"),
            match.get("duration"),
            match.get("start_time"),
            match.get("radiant_team_id"),
            match.get("radiant_name"),
            match.get("dire_team_id"),
            match.get("dire_name"),
            match.get("leagueid"),
            match.get("league_name"),
            match.get("series_id"),
            match.get("series_type"),
            match.get("radiant_score"),
            match.get("dire_score"),
            1 if match.get("radiant_win") else 0,
            match.get("version"),
        ))


def upsert_match_detail(conn: sqlite3.Connection, detail: dict, payload_json: str) -> None:
    """
    Insert or replace one full match detail row.

    This stores selected top-level fields in columns for easy querying and also
    stores the full raw JSON payload for future use.

    Args:
        conn: Open SQLite connection.
        detail: Dictionary returned by /matches/{match_id}.
        payload_json: JSON string version of the full detail payload.
    """
    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO matches (
              match_id, start_time, duration, radiant_win,
              radiant_score, dire_score, leagueid,
              series_id, series_type, game_mode, lobby_type,
              patch, region, replay_url, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            detail.get("match_id"),
            detail.get("start_time"),
            detail.get("duration"),
            1 if detail.get("radiant_win") else 0,
            detail.get("radiant_score"),
            detail.get("dire_score"),
            detail.get("leagueid"),
            detail.get("series_id"),
            detail.get("series_type"),
            detail.get("game_mode"),
            detail.get("lobby_type"),
            detail.get("patch"),
            detail.get("region"),
            detail.get("replay_url"),
            payload_json,
        ))

def get_missing_match_detail_ids(
    conn: sqlite3.Connection,
    limit: Optional[int] = None,
) -> list[int]:
    """
    Return match IDs that are known in match_index but do not yet have a row in matches.

    This is the main cost-control query for deciding which /matches/{match_id}
    calls still need to be made.

    Args:
        conn: Open SQLite connection.
        limit: Optional maximum number of IDs to return.

    Returns:
        A list of match IDs missing full detail rows.
    """
    sql = """
        SELECT mi.match_id
        FROM match_index mi
        LEFT JOIN matches m ON m.match_id = mi.match_id
        WHERE m.match_id IS NULL
        ORDER BY mi.match_id DESC
    """

    params: tuple = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)

    rows = conn.execute(sql, params).fetchall()
    return [row[0] for row in rows]

def get_missing_pro_match_detail_ids(
    conn: sqlite3.Connection,
    limit: Optional[int] = None,
) -> list[int]:
    """
    Return match IDs that exist in pro_matches but do not yet have full details in matches.

    This is useful when you want your detail fetcher to prioritize only pro matches.

    Args:
        conn: Open SQLite connection.
        limit: Optional maximum number of IDs to return.

    Returns:
        A list of pro match IDs missing full detail rows.
    """
    sql = """
        SELECT p.match_id
        FROM pro_matches p
        LEFT JOIN matches m ON m.match_id = p.match_id
        WHERE m.match_id IS NULL
        ORDER BY p.start_time DESC, p.match_id DESC
    """

    params: tuple = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)

    rows = conn.execute(sql, params).fetchall()
    return [row[0] for row in rows]

def match_detail_exists(conn: sqlite3.Connection, match_id: int) -> bool:
    """
    Check whether a full match detail row already exists.

    Args:
        conn: Open SQLite connection.
        match_id: The OpenDota match ID.

    Returns:
        True if the match already exists in the matches table, else False.
    """
    row = conn.execute("""
        SELECT 1
        FROM matches
        WHERE match_id = ?
        LIMIT 1;
    """, (match_id,)).fetchone()
    return row is not None

def pro_match_exists(conn: sqlite3.Connection, match_id: int) -> bool:
    """
    Check whether a pro match row already exists.

    Args:
        conn: Open SQLite connection.
        match_id: OpenDota match ID.

    Returns:
        True if the row exists in pro_matches, else False.
    """
    row = conn.execute("""
        SELECT 1
        FROM pro_matches
        WHERE match_id = ?
        LIMIT 1;
    """, (match_id,)).fetchone()
    return row is not None

def get_billing_period(dt: datetime | None = None) -> str:
    """
    Convert a datetime into a billing period string like '2026-03'.

    Args:
        dt: Optional datetime. If omitted, current local datetime is used.

    Returns:
        A YYYY-MM string representing the billing month.
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m")

def increment_api_usage(
    conn: sqlite3.Connection,
    provider: str,
    count: int = 1,
    billing_period: str | None = None,
) -> None:
    """
    Increment the API usage counter for a provider and billing period.

    If the row does not exist yet, it is created automatically.

    Args:
        conn: Open SQLite connection.
        provider: Name of the API provider, such as 'opendota'.
        count: Number of API calls to add.
        billing_period: Optional YYYY-MM billing period. If omitted, current month is used.
    """
    if billing_period is None:
        billing_period = get_billing_period()

    with conn:
        conn.execute("""
            INSERT INTO api_usage (provider, billing_period, call_count, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(provider, billing_period)
            DO UPDATE SET
              call_count = call_count + excluded.call_count,
              updated_at = CURRENT_TIMESTAMP;
        """, (provider, billing_period, count))

def get_api_usage(
    conn: sqlite3.Connection,
    provider: str,
    billing_period: str | None = None,
) -> int:
    """
    Get the stored API usage count for a provider and billing period.

    Args:
        conn: Open SQLite connection.
        provider: Name of the API provider, such as 'opendota'.
        billing_period: Optional YYYY-MM billing period. If omitted, current month is used.

    Returns:
        The number of recorded API calls for that month.
    """
    if billing_period is None:
        billing_period = get_billing_period()

    row = conn.execute("""
        SELECT call_count
        FROM api_usage
        WHERE provider = ? AND billing_period = ?;
    """, (provider, billing_period)).fetchone()

    return int(row[0]) if row else 0

def get_unnotified_long_pro_matches(
    conn: sqlite3.Connection,
    tournament_names: set[str],
    long_seconds: int,
    limit: int | None = None,
) -> list[dict]:
    """
    Return long pro matches in the selected tournaments that have not yet
    been notified to Discord.

    Args:
        conn: Open SQLite connection.
        tournament_names: Allowed tournament names.
        long_seconds: Long-match threshold in seconds.
        limit: Optional maximum number of rows to return.

    Returns:
        A list of match summary dictionaries.
    """
    if not tournament_names:
        return []

    placeholders = ",".join("?" for _ in tournament_names)

    sql = f"""
        SELECT
            match_id,
            duration,
            start_time,
            radiant_name,
            dire_name,
            league_name
        FROM pro_matches
        WHERE duration > ?
        AND long_notified_at IS NULL
        AND league_name IN ({placeholders})
        AND start_time >= strftime('%s','now','-30 days')
        ORDER BY start_time ASC, match_id ASC
    """

    params: list = [long_seconds, *sorted(tournament_names)]

    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(sql, params).fetchall()

    return [
        {
            "match_id": row[0],
            "duration": row[1],
            "start_time": row[2],
            "radiant_name": row[3],
            "dire_name": row[4],
            "league_name": row[5],
        }
        for row in rows
    ]


def mark_long_match_notified(conn: sqlite3.Connection, match_id: int) -> None:
    """
    Mark a pro match as having been notified as a long match.

    Args:
        conn: Open SQLite connection.
        match_id: OpenDota match ID.
    """
    with conn:
        conn.execute("""
            UPDATE pro_matches
            SET long_notified_at = CURRENT_TIMESTAMP
            WHERE match_id = ?;
        """, (match_id,))