#!/usr/bin/env python3
"""
app.py

Purpose:
Thin Flask layer over draft_engine.py / persistence.py / team_tendencies.py.
Routes only ever validate the HTTP request shape and translate
webapp.errors.DraftEngineError subclasses into JSON 4xx responses --
all actual composition logic lives in draft_engine.py (see that module's
docstring), so this file has essentially no business logic of its own.
Every route that returns a session wraps it in draft_engine.session_view()
so the frontend always gets the derived, non-persisted fields (current
Captain's Mode step, live elapsed seconds) alongside the raw state.

Run locally with:
    flask --app webapp.app run --debug

Location:
    webapp/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from flask import Flask, jsonify, request  # noqa: E402

from odds.hero_names import load_hero_names, resolve_hero  # noqa: E402
from odds.team_lookup import find_team_id  # noqa: E402
from webapp import draft_engine as de  # noqa: E402
from webapp import persistence  # noqa: E402
from webapp.errors import DraftEngineError, SessionNotFoundError  # noqa: E402

app = Flask(__name__, static_folder=str(Path(__file__).parent / "static"), static_url_path="")


@app.errorhandler(DraftEngineError)
def handle_draft_engine_error(err: DraftEngineError):
    return jsonify(err.to_dict()), err.status_code


def _load_or_404(match_session_id: str) -> dict:
    session = persistence.load_session(match_session_id)
    if session is None:
        raise SessionNotFoundError(f"No tracked match with id {match_session_id!r}.")
    return session


def _ok(session: dict, status: int = 200):
    return jsonify(de.session_view(session)), status


# ---------------------------------------------------------------------------
# Static pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return app.send_static_file("index.html")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

@app.route("/api/teams/search")
def search_teams():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []})
    pipeline = de.get_pipeline_data()
    lookup = find_team_id(q, pipeline.rating_names)
    if lookup.team_id is not None:
        return jsonify({"results": [{"team_id": lookup.team_id, "name": lookup.matched_name, "confidence": lookup.confidence}]})
    if lookup.candidates:
        return jsonify({"results": [], "candidates": lookup.candidates})
    return jsonify({"results": []})


@app.route("/api/heroes")
def list_heroes():
    names = load_hero_names()
    return jsonify({"heroes": [{"hero_id": hid, "name": name} for hid, name in sorted(names.items(), key=lambda kv: kv[1])]})


# ---------------------------------------------------------------------------
# Matchup / session lifecycle
# ---------------------------------------------------------------------------

@app.route("/api/matches", methods=["GET", "POST"])
def matches_collection():
    if request.method == "GET":
        return jsonify({"matches": persistence.list_sessions()})

    body = request.get_json(force=True) or {}
    session = de.create_matchup(
        body.get("team_a_query", ""), body.get("team_b_query", ""),
        body.get("first_pick_team", "team_a"),
    )
    return _ok(session, 201)


@app.route("/api/matches/<match_id>")
def get_match(match_id: str):
    return _ok(_load_or_404(match_id))


@app.route("/api/matches/<match_id>", methods=["DELETE"])
def delete_match(match_id: str):
    persistence.delete_session(match_id)
    return jsonify({"ok": True})


@app.route("/api/matches/<match_id>/dashboard")
def get_dashboard(match_id: str):
    session = _load_or_404(match_id)
    return jsonify(de.get_dashboard(session))


# ---------------------------------------------------------------------------
# Draft
# ---------------------------------------------------------------------------

@app.route("/api/matches/<match_id>/bans", methods=["POST"])
def post_ban(match_id: str):
    session = _load_or_404(match_id)
    body = request.get_json(force=True) or {}
    return _ok(de.record_ban(session, body["team"], body["hero_query"]))


@app.route("/api/matches/<match_id>/picks", methods=["POST"])
def post_pick(match_id: str):
    session = _load_or_404(match_id)
    body = request.get_json(force=True) or {}
    return _ok(de.record_pick(session, body["team"], body["hero_query"]))


@app.route("/api/matches/<match_id>/draft/undo", methods=["POST"])
def post_draft_undo(match_id: str):
    session = _load_or_404(match_id)
    return _ok(de.undo_last_draft_action(session))


@app.route("/api/matches/<match_id>/draft/finalize", methods=["POST"])
def post_draft_finalize(match_id: str):
    session = _load_or_404(match_id)
    return _ok(de.finalize_draft(session))


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

@app.route("/api/matches/<match_id>/assignment")
def get_assignment(match_id: str):
    session = _load_or_404(match_id)
    return jsonify(de.get_assignment_view(session))


@app.route("/api/matches/<match_id>/assignments", methods=["POST"])
def post_assignment(match_id: str):
    session = _load_or_404(match_id)
    body = request.get_json(force=True) or {}
    return _ok(de.assign_player(session, body["team"], int(body["hero_id"]), body.get("account_id")))


@app.route("/api/matches/<match_id>/assignment/finalize", methods=["POST"])
def post_assignment_finalize(match_id: str):
    session = _load_or_404(match_id)
    return _ok(de.finalize_assignment(session))


# ---------------------------------------------------------------------------
# Live match
# ---------------------------------------------------------------------------

@app.route("/api/matches/<match_id>/live/start", methods=["POST"])
def post_live_start(match_id: str):
    session = _load_or_404(match_id)
    body = request.get_json(force=True) or {}
    return _ok(de.start_live_match(session, body["radiant_team"]))


@app.route("/api/matches/<match_id>/live/starting", methods=["POST"])
def post_live_starting(match_id: str):
    session = _load_or_404(match_id)
    return _ok(de.mark_match_starting(session))


@app.route("/api/matches/<match_id>/live/pause", methods=["POST"])
def post_live_pause(match_id: str):
    session = _load_or_404(match_id)
    return _ok(de.pause_match(session))


@app.route("/api/matches/<match_id>/live/resume", methods=["POST"])
def post_live_resume(match_id: str):
    session = _load_or_404(match_id)
    return _ok(de.resume_match(session))


@app.route("/api/matches/<match_id>/live/events", methods=["POST"])
def post_live_event(match_id: str):
    session = _load_or_404(match_id)
    body = request.get_json(force=True) or {}
    return _ok(de.record_live_event(session, body))


@app.route("/api/matches/<match_id>/live/events/undo", methods=["POST"])
def post_live_event_undo(match_id: str):
    session = _load_or_404(match_id)
    return _ok(de.undo_last_live_event(session))


@app.route("/api/matches/<match_id>/live/gold", methods=["POST"])
def post_live_gold(match_id: str):
    session = _load_or_404(match_id)
    body = request.get_json(force=True) or {}
    return _ok(de.set_gold_lead(session, float(body["gold_lead"])))


@app.route("/api/matches/<match_id>/live/nudge", methods=["POST"])
def post_live_nudge(match_id: str):
    session = _load_or_404(match_id)
    body = request.get_json(force=True) or {}
    return _ok(de.set_manual_nudge(session, float(body["manual_nudge_pp"])))


@app.route("/api/matches/<match_id>/live/buyback", methods=["POST"])
def post_live_buyback(match_id: str):
    session = _load_or_404(match_id)
    body = request.get_json(force=True) or {}
    return _ok(de.toggle_buyback(session, int(body["hero_id"])))


@app.route("/api/matches/<match_id>/live/time", methods=["POST"])
def post_live_time(match_id: str):
    session = _load_or_404(match_id)
    body = request.get_json(force=True) or {}
    return _ok(de.set_time_correction(session, float(body["seconds"])))


@app.route("/api/matches/<match_id>/live/ancient", methods=["POST"])
def post_live_ancient(match_id: str):
    session = _load_or_404(match_id)
    body = request.get_json(force=True) or {}
    return _ok(de.end_match(session, body["team"]))


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@app.route("/api/system/refresh", methods=["POST"])
def post_system_refresh():
    de.get_pipeline_data(force_refresh=True)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)
