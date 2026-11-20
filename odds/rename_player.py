#!/usr/bin/env python3
"""
rename_player.py

Purpose:
Set a display-name override for a player: python3 odds/rename_player.py
<account_id> <name>. Equivalent to hand-editing
data/raw/player_name_overrides.json directly -- that file is plain JSON
({"account_id": "name", ...}), so it's just as easy to open it and edit
entries in place. This script exists for convenience/scripting.

Location:
    odds/rename_player.py
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from odds.player_names import OVERRIDES_PATH, load_name_overrides  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set a display-name override for a player.")
    parser.add_argument("account_id", type=int)
    parser.add_argument("name")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    overrides = load_name_overrides()
    was = overrides.get(args.account_id)
    overrides[args.account_id] = args.name

    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OVERRIDES_PATH.open("w") as f:
        json.dump({str(k): v for k, v in sorted(overrides.items())}, f, indent=2, ensure_ascii=False)
        f.write("\n")

    action = "Updated" if was else "Added"
    suffix = f" (was {was!r})" if was else ""
    print(f"{action} override: {args.account_id} -> {args.name!r}{suffix}")


if __name__ == "__main__":
    main()
