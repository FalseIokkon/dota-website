#!/usr/bin/env python3
import os
import json
import time
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

# --- Config ---
PROJECT_ROOT = "/home/tankionlinefirstseargent/projects/dota-website"
BACKEND_DIR = f"{PROJECT_ROOT}/backend"
DATA_DIR = f"{BACKEND_DIR}/data"
LOG_PATH = f"{BACKEND_DIR}/discord_webhook_log.txt"

TOURNAMENT_LIST_PATH = f"{BACKEND_DIR}/tournament_list.txt"
STATE_PATH = f"{BACKEND_DIR}/notified_long_matches.json"

LONG_SECONDS = 3600

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()


# log to backend/discord_webhook_log.txt
def log_line(s: str) -> None:
    Path(BACKEND_DIR).mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(s.rstrip("\n") + "\n")


def load_tournament_set() -> set:
    # tournament_list.txt appears to contain lines with trailing \n
    # We'll normalize by stripping and comparing stripped names.
    names = set()
    try:
        with open(TOURNAMENT_LIST_PATH, "r") as f:
            for line in f:
                name = line.strip()
                if name:
                    names.add(name)
    except FileNotFoundError:
        log_line(f"{datetime.now()}\tERROR: missing {TOURNAMENT_LIST_PATH}")
    return names


def load_state() -> set:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except Exception:
            pass
    return set()


def save_state(notified_ids: set) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sorted(list(notified_ids)), f)
    os.replace(tmp, STATE_PATH)


def pick_jsonl_path() -> str:
    year = datetime.now().year
    return f"{DATA_DIR}/{year}.jsonl"


def send_discord(content: str) -> bool:
    if not DISCORD_WEBHOOK_URL:
        log_line(f"{datetime.now()}\tWARN: DISCORD_WEBHOOK_URL not set; would send: {content}")
        return False

    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=15)
        if 200 <= r.status_code < 300:
            return True
        log_line(f"{datetime.now()}\tERROR: Discord webhook HTTP {r.status_code}: {r.text[:200]}")
        return False
    except requests.RequestException as e:
        log_line(f"{datetime.now()}\tERROR: Discord webhook failed: {e}")
        return False


def main():
    tournament_names = load_tournament_set()
    notified = load_state()

    jsonl_path = pick_jsonl_path()
    if not os.path.exists(jsonl_path):
        log_line(f"{datetime.now()}\tNo jsonl found at {jsonl_path}")
        return

    # Find all long matches (match_id) that are in tournament list
    long_matches = []
    with open(jsonl_path, "r") as f:
        for line in f:
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue

            # tournament filter
            league_name = (m.get("league_name") or "").strip()
            if league_name not in tournament_names:
                continue

            duration = m.get("duration")
            match_id = m.get("match_id")
            if match_id is None or duration is None:
                continue

            if duration > LONG_SECONDS:
                long_matches.append(m)

    # Sort to send in a stable order
    long_matches.sort(key=lambda x: x.get("match_id", 0))

    # Notify only new ones
    new_count = 0
    for m in long_matches:
        mid = m.get("match_id")
        if mid in notified:
            continue

        # Compose a helpful message
        radiant = (m.get("radiant_name") or "Radiant")
        dire = (m.get("dire_name") or "Dire")
        dur = m.get("duration", 0)
        mins = dur // 60
        first_digit = str(mins)[0]
        league = (m.get("league_name") or "Unknown League")
        masked_duration = f"{first_digit}x:xx"

        start_time = m.get("start_time")
        if start_time:
            local_dt = datetime.fromtimestamp(start_time)
            match_datetime = local_dt.astimezone().strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
        else:
            match_datetime = "Unknown start time"

        search_query = f"{league} {radiant} vs {dire}"
        encoded_query = quote_plus(search_query)
        youtube_url = f"https://www.youtube.com/results?search_query={encoded_query}"

        msg = (
            f"**Long Match Detected**\n"
            f"**{radiant} vs {dire}**\n"
            f"Date/Time: `{match_datetime}`\n"
            f"Duration: `{masked_duration}`\n"
            f"League: {league}\n"
            f"\n"
            f"🔎 [Dotabuff](https://www.dotabuff.com/matches/{mid})\n"
            f"▶️ [YouTube Search](<{youtube_url}>)\n"
            f"Match ID: `{mid}`"
        )


        ok = send_discord(msg)

        # Even if webhook is missing, we still mark it? Up to you.
        # I mark as notified only if Discord send succeeded.
        if ok:
            notified.add(mid)
            new_count += 1
            log_line(f"{datetime.now()}\tNOTIFIED long match {mid} ({masked_duration}) {radiant} vs {dire} [{league}]")
            time.sleep(0.3)  # tiny delay to be polite to Discord

    if new_count > 0:
        save_state(notified)
    log_line(f"{datetime.now()}\tScan complete. Found {len(long_matches)} long matches; sent {new_count} new notifications.")


if __name__ == "__main__":
    main()
