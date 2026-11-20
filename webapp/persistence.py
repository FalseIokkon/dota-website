#!/usr/bin/env python3
"""
persistence.py

Purpose:
One JSON file per tracked match under DATA_DIR/tracked_matches/, rewritten
after every mutating draft_engine call. Single local user, single browser
tab at a time in practice -- no locking/concurrency handling beyond an
atomic write (tmp file + os.replace) so a crash mid-write can't corrupt a
session file.

Sessions are plain dicts (see draft_engine.py's MatchSession shape) so this
module never needs to know the schema -- it just moves JSON in and out.

Location:
    webapp/persistence.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from core.config import DATA_DIR

SESSIONS_DIR = DATA_DIR / "tracked_matches"


def _session_path(match_session_id: str) -> Path:
    return SESSIONS_DIR / f"{match_session_id}.json"


def save_session(session: dict) -> None:
    """Atomically write a session dict to its JSON file, creating the directory on first use."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = _session_path(session["match_session_id"])
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(session, f, indent=2)
    os.replace(tmp_path, path)


def load_session(match_session_id: str) -> dict | None:
    """Returns the session dict, or None if no session with that id has been saved."""
    path = _session_path(match_session_id)
    if not path.exists():
        return None
    with path.open() as f:
        return json.load(f)


def list_sessions() -> list[dict]:
    """
    Lightweight summaries for the resume/past-matches list -- reads every
    file (fine at single-user scale; there's no separate index to keep in
    sync), returning just the fields index.html needs rather than full
    session bodies.
    """
    if not SESSIONS_DIR.exists():
        return []
    summaries = []
    for path in sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        with path.open() as f:
            session = json.load(f)
        summaries.append({
            "match_session_id": session["match_session_id"],
            "team_a_label": session["team_a"]["label"],
            "team_b_label": session["team_b"]["label"],
            "phase": session["phase"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        })
    return summaries


def delete_session(match_session_id: str) -> bool:
    path = _session_path(match_session_id)
    if not path.exists():
        return False
    path.unlink()
    return True
