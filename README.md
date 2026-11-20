# dotascript

A collection of scripts and automation tools for Dota 2 Pro Matches. This project started as a simple way parse through a large json list. Goals include logging entries into a database and applying data learning techniques, with findings published to a public website.

---

## Project layout

The repo is organized as a set of sibling Python projects, one per concern, sharing a common `core/` library:

- `core/` — shared config (`config.py`), SQLite helpers (`db.py`), and OpenDota API client (`opendota_client.py`). Every project imports from here rather than duplicating DB/config logic.
- `scraper/` — pulls pro matches and match details from OpenDota into the shared database (`dota.db`).
- `notifier/` — scans the database for long pro matches in watched tournaments and posts Discord alerts. Owns its own config (`tournament_list.txt`) and helper tool (`export_tournaments.py`) since nothing else uses them.
- `wards/` — extracts observer/sentry ward placements from stored match payloads and renders heatmaps.
- `odds/` — computes Glicko-2 ratings from `pro_matches` (org-level, and a player-level model that composites individual account ratings into a team's *current* lineup strength) and compares them against manually-entered moneyline odds to flag +EV bets. Also tracks hero-level signals: per-player hero affinity and current-patch hero meta strength (`hero_affinity.py`, `hero_meta.py`), combined into a win-probability adjustment (`hero_adjustment.py`) usable both pre-draft (`find_ev_bets.py --with-hero-fit`) and live during a draft (`live_draft.py`). See `odds/compute_ratings.py` (`--by-player`), `odds/run_backtest.py` (`--model both`), `odds/verify_lineups.py`, `odds/compute_hero_stats.py`, and `odds/find_ev_bets.py`.

Shared resources used by every project: `.env` (config/secrets), `data/` (raw/exports/derived), and `logs/`. Config that's only relevant to one project (like `notifier/tournament_list.txt`) lives inside that project's folder instead of a shared `config/` directory.

Each script under a project folder bootstraps imports the same way:

```python
REPO_ROOT = Path(__file__).resolve().parents[N]  # N = folder depth below repo root
sys.path.append(str(REPO_ROOT))
from core.config import ...
```

To add a new project, create a new top-level sibling folder and follow this same import pattern against `core/`.

---

## Notifier (long-match alerts + Discord bot)

Posts a Discord alert whenever a pro match in a watched tournament runs long, and lets you manage the watch list from Discord with slash commands.

### Pieces

| File | Runs | Does |
|---|---|---|
| `notifier/discord_notify_long_matches.py` | cron, every 5 min | Finds matches over `LONG_SECONDS` in tournaments listed in `tournament_list.txt`, posts each one to the channel webhook, then sets `pro_matches.long_notified_at` so it's never sent twice. |
| `notifier/export_tournaments.py` | cron, hourly (or `/refresh`) | Writes every `league_name` in the DB to `all_tournaments.txt`, oldest activity first. This feeds the bot's autocomplete. |
| `notifier/discord_bot.py` | always on, via `run_discord_bot.sh` | Slash commands for editing `tournament_list.txt`. |
| `notifier/run_discord_bot.sh` | `@reboot` cron, under `flock` | Restarts the bot 10s after any exit (it regularly drops on DNS/network timeouts and recovers). |
| `notifier/tournament_list.txt` | — | The watch list: one exact `league_name` per line. Matching is exact and case-sensitive. |

### Webhook vs. bot

These are two separate Discord integrations:

- **Alerts** go through a **webhook** (`DISCORD_WEBHOOK_URL`), a secret URL tied to one channel. Each alert is a single HTTP POST with no login or open connection, so a cron script that exits right away works.
- **The bot** (`DISCORD_BOT_TOKEN`) keeps a live connection to Discord in order to receive slash commands. It only replies ephemerally to whoever ran the command and never posts to channels. Commands are synced to one server (`DISCORD_GUILD_ID`), and every command refuses requests from any other server.

### Alert rules

Set in `discord_notify_long_matches.py` and `core/db.py::get_unnotified_long_pro_matches`:

- `LONG_SECONDS = 3000`: matches longer than 50 minutes. It was 3600 until 2026-11-20.
- Matches only qualify if they started in the last **30 days**.
- `MAX_NOTIFICATIONS_PER_RUN = 50`.
- A match qualifies only while `long_notified_at IS NULL`. Any value means it has been handled.
- The message masks the duration (e.g. `5x:xx`) to avoid spoilers, and links Dotabuff plus a YouTube VOD search.

**Lowering the threshold** makes every newly qualifying match from the last 30 days alert on the next run. To limit the backlog, mark the older ones as handled *before* changing the constant. This is what was done for the 60→50 change:

```sql
UPDATE pro_matches
SET long_notified_at = 'skipped: 50min threshold change 2026-11-20'
WHERE duration > 3000 AND duration <= 3600
  AND long_notified_at IS NULL
  AND start_time >= strftime('%s','now','-30 days')
  AND start_time <  strftime('%s','now','-3 days');
```

Use a descriptive text tag rather than a timestamp, so you can find the rows and undo it later (`SET long_notified_at = NULL WHERE long_notified_at = '<tag>'`).

### Bot commands

| Command | Does |
|---|---|
| `/track <tournament>` | Add a tournament to the watch list (autocompletes from `all_tournaments.txt`; warns if the name isn't known) |
| `/untrack <tournament>` | Remove a tournament from the watch list |
| `/tracked [count]` / `/tracked-all` | Show recent or all watched tournaments |
| `/tournaments [query]` / `/tournaments-all` | Search or list every tournament in the DB export |
| `/refresh` | Re-export tournaments **and** run the long-match check now instead of waiting for cron |
| `/help` | List commands |

`/refresh` runs the notifier under the same lock file as cron (`/tmp/discord_notify_long_matches.lock`, waiting up to 30s), so a manual run and a cron run can never send the same match twice. Alerts post to the webhook channel as usual; the command's reply only reports how many were found and sent.

### Applying changes

- **Notifier/export scripts:** nothing to do. Cron starts a fresh process each run.
- **`discord_bot.py`:** restart the bot with `pkill -f notifier/discord_bot.py`. The wrapper relaunches it with the new code within about 10s, and command changes are re-synced on startup.
- **Watch list:** use `/track` / `/untrack`, or edit `tournament_list.txt` directly. Both take effect on the next run.

### One-time bot setup (already done)

The script only *logs in*; it never joins servers itself. To recreate the bot:

1. Discord Developer Portal → New Application → Bot → copy the token into `.env` as `DISCORD_BOT_TOKEN`.
2. OAuth2 → URL Generator → scopes `bot` + `applications.commands` → open the URL and pick the server.
3. Enable Developer Mode in Discord, right-click the server → Copy Server ID → `DISCORD_GUILD_ID`.
4. Channel settings → Integrations → Webhooks → New Webhook → copy URL → `DISCORD_WEBHOOK_URL`.

Keep the token and webhook URL secret. Anyone holding them can control the bot or post to the channel.

### Config, logs, and gotchas

- **`.env` keys used:** `PROJECT_ROOT`, `DB_PATH`, `DISCORD_WEBHOOK_URL`, `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`.
- **The database is not in the repo.** `DB_PATH` points to the data drive under `/mnt`. Always query it by that path; running `sqlite3 data/dota.db` silently creates an empty file in the repo instead of failing.
- **Logs** (in `logs/`): `discord_notify_long_matches.log` (every run and alert), `discord_bot.log` (command actions), and `discord_bot_wrapper.log` (bot stdout, crashes and restarts). Nothing rotates these.
- **`long_notified_at` is not created by `core/db.py::create_tables`.** It was added to the live DB by hand. On a fresh DB, run `ALTER TABLE pro_matches ADD COLUMN long_notified_at TEXT;` first, or the notifier will fail.
- **Duplicate lines in `tournament_list.txt`:** `/untrack` removes only one copy, so the tournament stays watched. Keep the file free of duplicates.

