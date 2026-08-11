# dotascript

A collection of scripts and automation tools for Dota 2 Pro Matches. This project started as a simple way parse through a large json list. Goals include logging entries into a database and applying data learning techniques, with findings published to a public website.

---

## Project layout

The repo is organized as a set of sibling Python projects, one per concern, sharing a common `core/` library:

- `core/` — shared config (`config.py`), SQLite helpers (`db.py`), and OpenDota API client (`opendota_client.py`). Every project imports from here rather than duplicating DB/config logic.
- `scraper/` — pulls pro matches and match details from OpenDota into the shared database (`dota.db`).
- `notifier/` — scans the database for long pro matches in watched tournaments and posts Discord alerts. Owns its own config (`tournament_list.txt`) and helper tool (`export_tournaments.py`) since nothing else uses them.
- `wards/` — extracts observer/sentry ward placements from stored match payloads and renders heatmaps.
- `odds/` — (placeholder) future project to compute team ratings and matchup odds.

Shared resources used by every project: `.env` (config/secrets), `data/` (raw/exports/derived), and `logs/`. Config that's only relevant to one project (like `notifier/tournament_list.txt`) lives inside that project's folder instead of a shared `config/` directory.

Each script under a project folder bootstraps imports the same way:

```python
REPO_ROOT = Path(__file__).resolve().parents[N]  # N = folder depth below repo root
sys.path.append(str(REPO_ROOT))
from core.config import ...
```

To add a new project, create a new top-level sibling folder and follow this same import pattern against `core/`.

