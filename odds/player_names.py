#!/usr/bin/env python3
"""
player_names.py

Purpose:
Resolve account_id -> OpenDota's curated pro-player name (e.g. "9Class"),
as opposed to the flaky, frequently-changed Steam personaname already
stored in lineups.csv (e.g. "Pele"). This project's own display of
"current lineup" has repeatedly shown joke/unrelated nicknames instead of
recognizable competitive handles -- this is the fix.

Caches results to data/derived/player_names.json since OpenDota's curated
name changes rarely; see fetch_player_names.py for the bulk-fetch CLI that
populates this cache (one HTTP request per uncached account_id, so it's
deliberately not called inline by every script -- run it once, then
load_player_names() reads the cache).

Location:
    odds/player_names.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "derived" / "player_names.json"

# User-editable: account_id -> whatever name you want shown. Unlike
# CACHE_PATH (a generated cache, overwritten by fetch_player_names.py),
# this lives in data/raw/ and is never written to except by you (directly,
# or via generate_player_name_overrides.py / rename_player.py). Takes
# priority over everything else in display_name().
OVERRIDES_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "player_name_overrides.json"

# Polite pacing between OpenDota player-profile requests. Not documented as
# strictly required (unlike Liquipedia's explicit per-endpoint limits, which
# this project got rate-limited by earlier for ignoring), but this project
# already leans on OpenDota heavily elsewhere (scraper/) and there's no
# reason to hammer it just because a handful of requests are cheap. Measured
# in practice: ~60 unauthenticated requests at 0.5s spacing was enough to
# trip a 429, so this backs off and retries rather than just giving up.
REQUEST_DELAY_SECONDS = 1.0
RATE_LIMIT_BACKOFF_SECONDS = 15.0
MAX_RETRIES = 2


def load_player_names() -> dict[int, str]:
    """
    Load the cached account_id -> curated name mapping.

    Returns:
        Mapping of int account_id to name. Empty dict if the cache hasn't
        been built yet -- run fetch_player_names.py first.
    """
    if not CACHE_PATH.exists():
        return {}
    with CACHE_PATH.open() as f:
        raw = json.load(f)
    return {int(account_id): name for account_id, name in raw.items()}


def load_name_overrides() -> dict[int, str]:
    """
    Load your manual account_id -> display name overrides from
    data/raw/player_name_overrides.json. Edit that file directly (it's
    plain JSON: {"account_id": "name", ...}) or use rename_player.py /
    generate_player_name_overrides.py to manage it.

    Returns:
        Mapping of int account_id to your preferred name. Empty dict if the
        file doesn't exist yet.
    """
    if not OVERRIDES_PATH.exists():
        return {}
    with OVERRIDES_PATH.open() as f:
        raw = json.load(f)
    return {int(account_id): name for account_id, name in raw.items()}


def display_name(account_id, curated: dict[int, str], personaname_map: dict) -> str:
    """
    Best available display name for an account_id: your own manual override
    (data/raw/player_name_overrides.json) first, then OpenDota's curated
    pro name if we've fetched it, else whatever personaname is on file,
    else the raw account_id as a last resort.

    Args:
        account_id: The player's account_id.
        curated: Output of load_player_names().
        personaname_map: account_id -> personaname, e.g.
            player_ratings.PlayerPipelineResult.names.

    Returns:
        The name to show the user.
    """
    overrides = load_name_overrides()
    if isinstance(account_id, int) and account_id in overrides:
        return overrides[account_id]
    if isinstance(account_id, int) and account_id in curated:
        return curated[account_id]
    return personaname_map.get(account_id, str(account_id))


def fetch_and_cache_player_names(account_ids: list[int], client, force: bool = False) -> dict[int, str]:
    """
    Fetch OpenDota's curated name for each account_id not already cached
    (or all of them, if force=True), merge into the existing cache, and
    save it back.

    Args:
        account_ids: Steam32 account IDs to resolve.
        client: A core.opendota_client.OpenDotaClient instance.
        force: Re-fetch even for account_ids already in the cache.

    Returns:
        The full updated cache (not just the newly-fetched entries).
    """
    cache = load_player_names()
    to_fetch = account_ids if force else [a for a in account_ids if a not in cache]

    for i, account_id in enumerate(to_fetch):
        profile = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                profile = client.get_player(account_id).get("profile", {})
                break
            except requests.HTTPError as e:
                is_rate_limited = e.response is not None and e.response.status_code == 429
                if is_rate_limited and attempt < MAX_RETRIES:
                    print(f"[INFO] Rate limited on account_id={account_id}, backing off {RATE_LIMIT_BACKOFF_SECONDS:.0f}s...")
                    time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
                    continue
                print(f"[WARN] Failed to fetch account_id={account_id}: {e}")
            except Exception as e:
                print(f"[WARN] Failed to fetch account_id={account_id}: {e}")
                break

        if profile is None:
            if i < len(to_fetch) - 1:
                time.sleep(REQUEST_DELAY_SECONDS)
            continue

        name = profile.get("name") or profile.get("personaname")
        if name:
            cache[account_id] = name
        else:
            print(f"[INFO] No curated or persona name found for account_id={account_id}")

        if i < len(to_fetch) - 1:
            time.sleep(REQUEST_DELAY_SECONDS)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w") as f:
        json.dump({str(k): v for k, v in cache.items()}, f, indent=2, ensure_ascii=False)

    return cache
