#!/usr/bin/env python3
"""
draft_engine.py

Purpose:
Composition core for the draft/assignment/live match-tracking GUI. Wires
together the same odds/ pieces odds/live_draft.py already uses for its
terminal REPL, replacing that script's input()/print() loop with plain
functions operating on a session dict (see MatchSession shape below) that
app.py exposes over HTTP and persistence.py saves to disk after every
mutation.

No Flask/HTTP knowledge here on purpose -- every function takes/returns
plain dicts and raises webapp.errors.DraftEngineError subclasses on bad
input, so this whole module is exercisable directly from a Python REPL
(there is no test suite in this repo to lean on instead).

Win-probability composition, three stages, one reused function
(odds.hero_adjustment.adjust_probability): picks are stored as
(account_id, hero_id) pairs where account_id is None until a player is
assigned. Passing account_id=None makes that pick's affinity_delta
silently resolve to 0 (dict lookup miss in hero_affinity's table) --
so the exact same call naturally produces a meta/ban-pressure-only
probability during the draft, and layers in real per-player affinity as
assign_player() fills in real account_ids, with zero forking of that
function.

Bans don't move adjust_probability at all (its ban_pressure_delta term is
about a *picked* hero's own aggregate historical ban rate, not "was this
hero banned in this specific draft") -- so record_ban applies a small,
separately-computed "ban-denial" heuristic on top: the banning team gets
credit proportional to how strong the banned hero currently is
(hero_meta.win_rate_shrunk - 0.5), scaled by BAN_DENIAL_SCALE. Same
disclaimed-heuristic spirit as hero_adjustment.py's own constants.

Location:
    webapp/draft_engine.py
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from core.config import DB_PATH
from odds import glicko2
from odds.hero_adjustment import MAX_PROB, MIN_PROB, adjust_probability
from odds.hero_affinity import compute_hero_affinity, top_heroes
from odds.hero_meta import compute_hero_meta, current_patch
from odds.hero_names import load_hero_names, resolve_hero
from odds.player_names import display_name, load_player_names
from odds.player_ratings import build_current_player_ratings, composite_rating
from odds.ratings import build_current_ratings
from odds.ti2026_teams import apply_lineup_overrides, resolve_team_id

from . import live_events, persistence
from .errors import HeroResolutionError, InvalidActionError, TeamResolutionError
from .team_tendencies import compute_team_pick_ban_tendencies

# Banning a hero grants the banning team a probability credit proportional
# to (hero_meta.win_rate_shrunk - 0.5) * BAN_DENIAL_SCALE -- e.g. banning a
# 58%-shrunk-win-rate hero (0.08 above neutral) at the default scale is
# worth 0.08 * 0.25 = 2 probability points to the team that banned it.
# Unvalidated starting weight, same caveat as every other constant in this
# codebase's hero/live adjustment modules.
BAN_DENIAL_SCALE = 0.25

OTHER_TEAM = {"team_a": "team_b", "team_b": "team_a"}

# Current ("New Captain's Mode", 7.33+) Dota 2 draft order: 7 bans + 5 picks
# per side, 24 actions total, in six phases -- ban x7, pick x2, ban x3,
# pick x6, ban x4, pick x2. "first"/"second" are relative to whichever team
# won ban-1 (see session["first_pick_team"]), resolved to team_a/team_b at
# validation time. Reconstructed from the current Dota 2 Wiki "Captain's
# Mode picking order" reference graphic -- the six phase sizes/totals are
# certain (they're constrained to sum to 7 bans/5 picks per side), the
# exact alternation *within* the two longest phases (6-pick and the second
# 7-ban) is a best-effort reconstruction; nudge DRAFT_SEQUENCE directly if
# any single step turns out to not match the wiki.
DRAFT_SEQUENCE: list[tuple[str, str]] = [
    ("ban", "first"), ("ban", "second"), ("ban", "first"), ("ban", "second"),
    ("ban", "first"), ("ban", "second"), ("ban", "second"),
    ("pick", "first"), ("pick", "second"),
    ("ban", "first"), ("ban", "second"), ("ban", "first"),
    ("pick", "second"), ("pick", "first"), ("pick", "second"),
    ("pick", "first"), ("pick", "second"), ("pick", "first"),
    ("ban", "second"), ("ban", "first"), ("ban", "second"), ("ban", "first"),
    ("pick", "second"), ("pick", "first"),
]


def _resolve_relative_team(session: dict, relative: str) -> str:
    first = session["first_pick_team"]
    return first if relative == "first" else OTHER_TEAM[first]


def current_draft_step(session: dict) -> dict | None:
    """The next required (type, team) in the fixed sequence, or None once all 24 actions are done."""
    index = len(session["bans"]) + len(session["picks"])
    if index >= len(DRAFT_SEQUENCE):
        return None
    action_type, relative = DRAFT_SEQUENCE[index]
    return {"index": index, "type": action_type, "team": _resolve_relative_team(session, relative)}


@dataclass
class PipelineData:
    """Cached, expensive-to-build inputs shared by every session. Rebuilt only on force_refresh."""
    rating_names: dict = field(default_factory=dict)
    player_result: object = None
    affinity: dict = field(default_factory=dict)
    hero_meta: dict = field(default_factory=dict)
    hero_names: dict = field(default_factory=dict)
    player_names: dict = field(default_factory=dict)
    team_tendencies: dict = field(default_factory=dict)
    patch: int = 0


_pipeline_cache: PipelineData | None = None


def get_pipeline_data(force_refresh: bool = False) -> PipelineData:
    """
    Load (or reuse the cached) rating/hero/team data every session needs.
    Takes a few seconds the first time (same cost live_draft.py's main()
    pays inline) -- cached at module scope so repeated HTTP requests don't
    re-pay it.
    """
    global _pipeline_cache
    if _pipeline_cache is not None and not force_refresh:
        return _pipeline_cache

    db_path = str(DB_PATH)
    rating_result = build_current_ratings(db_path)
    player_result = build_current_player_ratings(db_path)

    _pipeline_cache = PipelineData(
        rating_names=rating_result.names,
        player_result=player_result,
        affinity=compute_hero_affinity(db_path),
        hero_meta=compute_hero_meta(db_path),
        hero_names=load_hero_names(),
        player_names=load_player_names(),
        team_tendencies=compute_team_pick_ban_tendencies(db_path),
        patch=current_patch(db_path),
    )
    return _pipeline_cache


def _resolve_roster(team_query: str, pipeline: PipelineData) -> tuple[int, list, str, str]:
    """Mirrors live_draft.py's resolve_roster, raising instead of sys.exit on failure."""
    lookup = resolve_team_id(team_query, pipeline.rating_names)
    if lookup.team_id is None:
        if lookup.confidence == "ambiguous":
            raise TeamResolutionError(f"{team_query!r} matches multiple teams.", candidates=lookup.candidates)
        raise TeamResolutionError(f"Could not resolve team name to a rated team: {team_query!r}")

    display_label = lookup.canonical or lookup.matched_name or team_query
    lineup = pipeline.player_result.current_lineup_by_team.get(lookup.team_id)
    if not lineup:
        raise TeamResolutionError(f"No cached lineup for {team_query!r} (team_id={lookup.team_id}).")
    patched = apply_lineup_overrides(lookup.canonical or team_query, lineup)
    return lookup.team_id, patched, display_label, lookup.confidence


def _log(session: dict, phase: str, description: str, prob_a: float) -> None:
    session["prob_log"].append({"phase": phase, "description": description, "prob_a": prob_a, "ts": time.time()})


def _touch(session: dict) -> None:
    session["updated_at"] = time.time()


# ---------------------------------------------------------------------------
# Matchup creation
# ---------------------------------------------------------------------------

def create_matchup(team_a_query: str, team_b_query: str, first_pick_team: str = "team_a") -> dict:
    if first_pick_team not in ("team_a", "team_b"):
        raise InvalidActionError("first_pick_team must be 'team_a' or 'team_b'.")
    pipeline = get_pipeline_data()
    team_a_id, team_a_ids, team_a_label, team_a_conf = _resolve_roster(team_a_query, pipeline)
    team_b_id, team_b_ids, team_b_label, team_b_conf = _resolve_roster(team_b_query, pipeline)

    rating_a = composite_rating([pipeline.player_result.effective_rating(a) for a in team_a_ids])
    rating_b = composite_rating([pipeline.player_result.effective_rating(a) for a in team_b_ids])
    base_prob_a = glicko2.expected_score(rating_a, rating_b)

    now = time.time()
    session = {
        "match_session_id": uuid.uuid4().hex[:12],
        "created_at": now,
        "updated_at": now,
        "phase": "draft",
        "first_pick_team": first_pick_team,
        "team_a": {"team_id": team_a_id, "label": team_a_label, "query": team_a_query, "confidence": team_a_conf},
        "team_b": {"team_id": team_b_id, "label": team_b_label, "query": team_b_query, "confidence": team_b_conf},
        "roster": {"team_a": team_a_ids, "team_b": team_b_ids},
        "base_prob_a": base_prob_a,
        "draft_prob_a": base_prob_a,
        "assigned_prob_a": None,
        "live_prob_a": None,
        "bans": [],
        "picks": [],
        "assignments": {"team_a": {}, "team_b": {}},
        "radiant_team": None,
        "live": {
            "status": "pending",  # pending | live | paused | ended -- mirrors the timer, distinct from session["phase"]
            "started_at": None,
            "paused_at": None,
            "total_paused_seconds": 0.0,
            "time_correction": 0.0,
            "destroyed_objectives": [],
            "events": [],
            "gold_lead": 0.0,
            "manual_nudge_pp": 0.0,
            "buybacks": {},
            "breakdown": {"event_total_pp": 0.0, "gold_contribution_pp": 0.0, "manual_nudge_pp": 0.0},
            "ended": False,
            "winner": None,
        },
        "prob_log": [],
    }
    _log(session, "draft", f"{team_a_label} vs {team_b_label} -- base rating", base_prob_a)
    persistence.save_session(session)
    return session


# ---------------------------------------------------------------------------
# Draft: bans + picks
# ---------------------------------------------------------------------------

def _used_hero_ids(session: dict) -> set[int]:
    return {b["hero_id"] for b in session["bans"]} | {p["hero_id"] for p in session["picks"]}


def _resolve_hero_query(hero_query: str, pipeline: PipelineData, used: set[int]) -> tuple[int, str]:
    lookup = resolve_hero(hero_query, pipeline.hero_names)
    if lookup.confidence == "ambiguous":
        raise HeroResolutionError(f"{hero_query!r} matches multiple heroes.", candidates=lookup.candidates)
    if lookup.hero_id is None:
        raise HeroResolutionError(f"Could not resolve hero {hero_query!r}.")
    if lookup.hero_id in used:
        raise InvalidActionError(f"{lookup.matched_name} is already picked or banned in this draft.")
    return lookup.hero_id, lookup.matched_name


def _recompute_draft_prob(session: dict, pipeline: PipelineData) -> float:
    """Stage-1 probability: picks only, account_id=None (see module docstring)."""
    picks_a = [(None, p["hero_id"]) for p in session["picks"] if p["team"] == "team_a"]
    picks_b = [(None, p["hero_id"]) for p in session["picks"] if p["team"] == "team_b"]
    return adjust_probability(session["base_prob_a"], picks_a, picks_b, pipeline.affinity, pipeline.hero_meta)


def _check_sequence(session: dict, action_type: str, team: str) -> None:
    step = current_draft_step(session)
    if step is None:
        raise InvalidActionError("The draft is already complete (all 24 Captain's Mode actions are done).")
    if step["type"] != action_type or step["team"] != team:
        expected_label = f"{session[step['team']]['label']} to {step['type']}"
        raise InvalidActionError(f"Out of sequence -- next up is {expected_label} (step {step['index'] + 1}/24).")


def _maybe_advance_to_assignment(session: dict) -> None:
    if current_draft_step(session) is None and session["phase"] == "draft":
        session["phase"] = "assignment"
        session["assigned_prob_a"] = session["draft_prob_a"]
        _log(session, "assignment", "Draft complete -- all 24 Captain's Mode actions done", session["assigned_prob_a"])


def record_ban(session: dict, team: str, hero_query: str) -> dict:
    if session["phase"] != "draft":
        raise InvalidActionError(f"Cannot ban -- draft phase already finished (session is '{session['phase']}').")
    _check_sequence(session, "ban", team)
    pipeline = get_pipeline_data()
    hero_id, hero_name = _resolve_hero_query(hero_query, pipeline, _used_hero_ids(session))

    session["bans"].append({"order": len(session["bans"]) + len(session["picks"]), "team": team, "hero_id": hero_id, "ts": time.time()})

    meta = pipeline.hero_meta.get(hero_id)
    denial = (meta.win_rate_shrunk - 0.5) * BAN_DENIAL_SCALE if meta else 0.0
    signed = denial if team == "team_a" else -denial
    session["draft_prob_a"] = min(max(session["draft_prob_a"] + signed, MIN_PROB), MAX_PROB)

    team_label = session[team]["label"]
    note = "" if denial == 0 else f" (denial {denial * 100:+.1f}pp)"
    _log(session, "draft", f"{team_label} banned {hero_name}{note}", session["draft_prob_a"])
    _maybe_advance_to_assignment(session)
    _touch(session)
    persistence.save_session(session)
    return session


def record_pick(session: dict, team: str, hero_query: str) -> dict:
    if session["phase"] != "draft":
        raise InvalidActionError(f"Cannot pick -- draft phase already finished (session is '{session['phase']}').")
    _check_sequence(session, "pick", team)
    pipeline = get_pipeline_data()
    hero_id, hero_name = _resolve_hero_query(hero_query, pipeline, _used_hero_ids(session))

    session["picks"].append({"order": len(session["bans"]) + len(session["picks"]), "team": team, "hero_id": hero_id, "ts": time.time()})
    session["draft_prob_a"] = _recompute_draft_prob(session, pipeline)

    team_label = session[team]["label"]
    _log(session, "draft", f"{team_label} picked {hero_name}", session["draft_prob_a"])
    _maybe_advance_to_assignment(session)
    _touch(session)
    persistence.save_session(session)
    return session


def undo_last_draft_action(session: dict) -> dict:
    """Replay-from-log: drop the most recent ban or pick, recompute forward from what remains."""
    if session["phase"] not in ("draft", "assignment") or session["assignments"]["team_a"] or session["assignments"]["team_b"]:
        raise InvalidActionError("Cannot undo a draft action once player assignment has started.")
    session["phase"] = "draft"  # undoing the 24th action re-opens the draft even if it had auto-completed
    last_ban = session["bans"][-1] if session["bans"] else None
    last_pick = session["picks"][-1] if session["picks"] else None
    if last_ban is None and last_pick is None:
        raise InvalidActionError("Nothing to undo.")

    if last_pick and (last_ban is None or last_pick["order"] > last_ban["order"]):
        session["picks"].pop()
    else:
        session["bans"].pop()

    pipeline = get_pipeline_data()
    # Bans' ban-denial deltas aren't individually reversible from draft_prob_a
    # alone (it's just a running float) -- replay them all fresh from base_prob_a.
    session["draft_prob_a"] = _recompute_draft_prob(session, pipeline)
    for b in session["bans"]:
        meta = pipeline.hero_meta.get(b["hero_id"])
        denial = (meta.win_rate_shrunk - 0.5) * BAN_DENIAL_SCALE if meta else 0.0
        signed = denial if b["team"] == "team_a" else -denial
        session["draft_prob_a"] = min(max(session["draft_prob_a"] + signed, MIN_PROB), MAX_PROB)

    _log(session, "draft", "Undo last draft action", session["draft_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


def finalize_draft(session: dict) -> dict:
    if session["phase"] != "draft":
        raise InvalidActionError(f"Session is already past the draft phase ('{session['phase']}').")
    session["phase"] = "assignment"
    session["assigned_prob_a"] = session["draft_prob_a"]
    _log(session, "assignment", "Draft finalized", session["assigned_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


# ---------------------------------------------------------------------------
# Player assignment
# ---------------------------------------------------------------------------

def assign_player(session: dict, team: str, hero_id: int, account_id: int | None) -> dict:
    if session["phase"] != "assignment":
        raise InvalidActionError(f"Cannot assign players -- session is '{session['phase']}', not 'assignment'.")
    picked_hero_ids = {p["hero_id"] for p in session["picks"] if p["team"] == team}
    if hero_id not in picked_hero_ids:
        raise InvalidActionError(f"Hero {hero_id} was not picked by {team} in this draft.")

    if account_id is None:
        session["assignments"][team].pop(str(hero_id), None)
    else:
        # A player can only be on one hero at a time -- unassign them elsewhere first.
        for other_hero_id, other_account in list(session["assignments"][team].items()):
            if other_account == account_id and int(other_hero_id) != hero_id:
                del session["assignments"][team][other_hero_id]
        session["assignments"][team][str(hero_id)] = account_id

    pipeline = get_pipeline_data()
    picks_a = _assigned_picks(session, "team_a")
    picks_b = _assigned_picks(session, "team_b")
    session["assigned_prob_a"] = adjust_probability(session["base_prob_a"], picks_a, picks_b, pipeline.affinity, pipeline.hero_meta)

    hero_name = pipeline.hero_names.get(hero_id, f"hero_{hero_id}")
    if account_id is None:
        desc = f"Cleared player assignment for {hero_name} ({session[team]['label']})"
    else:
        name = display_name(account_id, pipeline.player_names, {})
        desc = f"{session[team]['label']}: {name} -> {hero_name}"
    _log(session, "assignment", desc, session["assigned_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


def _assigned_picks(session: dict, team: str) -> list[tuple]:
    """(account_id_or_None, hero_id) for every pick this team made -- see module docstring's reuse trick."""
    assignments = session["assignments"][team]
    result = []
    for p in session["picks"]:
        if p["team"] != team:
            continue
        account_id = assignments.get(str(p["hero_id"]))
        result.append((account_id, p["hero_id"]))
    return result


def finalize_assignment(session: dict) -> dict:
    if session["phase"] != "assignment":
        raise InvalidActionError(f"Session is not in the assignment phase ('{session['phase']}').")
    session["phase"] = "ready"
    _touch(session)
    persistence.save_session(session)
    return session


def start_live_match(session: dict, radiant_team: str) -> dict:
    if session["phase"] not in ("assignment", "ready"):
        raise InvalidActionError(f"Cannot start the live match from phase '{session['phase']}'.")
    if radiant_team not in ("team_a", "team_b"):
        raise InvalidActionError("radiant_team must be 'team_a' or 'team_b'.")

    session["phase"] = "live"
    session["radiant_team"] = radiant_team
    session["live_prob_a"] = _recompute_live_prob(session)
    _log(session, "live", "Moved to live tracking", session["live_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


def mark_match_starting(session: dict) -> dict:
    """Zeroes the clock -- separate from start_live_match so re-clicking 'Match Starting' (e.g. once the stream actually begins) doesn't require re-picking Radiant/Dire."""
    if session["phase"] != "live":
        raise InvalidActionError(f"Cannot start the clock -- session is '{session['phase']}', not 'live'.")
    session["live"]["status"] = "live"
    session["live"]["started_at"] = time.time()
    session["live"]["paused_at"] = None
    session["live"]["total_paused_seconds"] = 0.0
    session["live"]["time_correction"] = 0.0
    _log(session, "live", "Match starting", session["live_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


def pause_match(session: dict) -> dict:
    if session["live"]["status"] != "live":
        raise InvalidActionError(f"Cannot pause -- clock is '{session['live']['status']}', not 'live'.")
    session["live"]["status"] = "paused"
    session["live"]["paused_at"] = time.time()
    _log(session, "live", "Match paused", session["live_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


def resume_match(session: dict) -> dict:
    if session["live"]["status"] != "paused":
        raise InvalidActionError(f"Cannot resume -- clock is '{session['live']['status']}', not 'paused'.")
    session["live"]["total_paused_seconds"] += time.time() - session["live"]["paused_at"]
    session["live"]["paused_at"] = None
    session["live"]["status"] = "live"
    _log(session, "live", "Match resumed", session["live_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


# ---------------------------------------------------------------------------
# Live match tracking
# ---------------------------------------------------------------------------

def _recompute_live_prob(session: dict) -> float:
    events = [live_events.LiveEvent(**e["event"]) for e in session["live"]["events"]]
    gold_lead = session["live"]["gold_lead"]
    manual_nudge_pp = session["live"]["manual_nudge_pp"]
    session["live"]["breakdown"] = live_events.compute_live_breakdown(events, gold_lead, manual_nudge_pp)
    return live_events.compute_live_prob_a(session["assigned_prob_a"], events, gold_lead, manual_nudge_pp)


def _credited_team_for_hero(session: dict, hero_id: int) -> str | None:
    for team in ("team_a", "team_b"):
        if str(hero_id) in session["assignments"][team]:
            return team
    for p in session["picks"]:
        if p["hero_id"] == hero_id:
            return p["team"]
    return None


def record_live_event(session: dict, event: dict) -> dict:
    if session["phase"] != "live":
        raise InvalidActionError(f"Cannot record a live event -- session is '{session['phase']}', not 'live'.")

    credited_team = event.get("credited_team")
    hero_id = event.get("hero_id")
    if credited_team is None and hero_id is not None:
        credited_team = _credited_team_for_hero(session, hero_id)
    if credited_team not in ("team_a", "team_b"):
        raise InvalidActionError("Could not determine which team to credit for this event.")
    event["credited_team"] = credited_team

    live_event = live_events.LiveEvent(**event)
    delta = live_events.signed_delta(live_event)

    session["live"]["events"].append({"seq": len(session["live"]["events"]), "ts_wall": time.time(), "event": event, "delta": delta})
    if event.get("objective_id"):
        session["live"]["destroyed_objectives"].append(event["objective_id"])

    session["live_prob_a"] = _recompute_live_prob(session)

    pipeline = get_pipeline_data()
    team_label = session[credited_team]["label"]
    hero_name = pipeline.hero_names.get(hero_id, "") if hero_id else ""
    desc = _describe_event(event, team_label, hero_name)
    _log(session, "live", desc, session["live_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


def _describe_event(event: dict, team_label: str, hero_name: str) -> str:
    et = event["event_type"]
    who = f" ({hero_name})" if hero_name else ""
    if et == "kill":
        return f"{team_label} kill{who}"
    if et == "roshan":
        return f"{team_label} got Roshan{who}"
    if et == "tormentor":
        return f"{team_label} got a Tormentor{who}"
    if et == "building":
        bt = event.get("building_type", "building")
        tier = event.get("tier")
        lane = event.get("lane", "")
        tier_note = f" T{tier}" if tier else ""
        rax = f" {event.get('rax_type')}" if event.get("rax_type") else ""
        return f"{team_label} destroyed {lane}{tier_note}{rax} {bt}".strip().replace("  ", " ")
    return f"{team_label} event: {et}"


def undo_last_live_event(session: dict) -> dict:
    if session["phase"] != "live":
        raise InvalidActionError("Cannot undo -- session is not in the live phase.")
    if not session["live"]["events"]:
        raise InvalidActionError("No live events to undo.")
    last = session["live"]["events"].pop()
    objective_id = last["event"].get("objective_id")
    if objective_id and objective_id in session["live"]["destroyed_objectives"]:
        session["live"]["destroyed_objectives"].remove(objective_id)
    session["live_prob_a"] = _recompute_live_prob(session)
    _log(session, "live", "Undo last live event", session["live_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


def set_gold_lead(session: dict, gold_lead: float) -> dict:
    if session["phase"] != "live":
        raise InvalidActionError("Gold lead can only be set during the live phase.")
    session["live"]["gold_lead"] = gold_lead
    session["live_prob_a"] = _recompute_live_prob(session)
    _log(session, "live", f"Gold lead set to {gold_lead:+.0f}", session["live_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


def set_manual_nudge(session: dict, manual_nudge_pp: float) -> dict:
    if session["phase"] != "live":
        raise InvalidActionError("The manual nudge can only be set during the live phase.")
    session["live"]["manual_nudge_pp"] = manual_nudge_pp
    session["live_prob_a"] = _recompute_live_prob(session)
    _log(session, "live", f"Manual nudge set to {manual_nudge_pp * 100:+.1f}pp", session["live_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


def toggle_buyback(session: dict, hero_id: int) -> dict:
    if session["phase"] != "live":
        raise InvalidActionError("Buyback can only be tracked during the live phase.")
    key = str(hero_id)
    active = not session["live"]["buybacks"].get(key, False)
    session["live"]["buybacks"][key] = active

    pipeline = get_pipeline_data()
    hero_name = pipeline.hero_names.get(hero_id, f"hero_{hero_id}")
    state = "used" if active else "available"
    _log(session, "live", f"Buyback {state}: {hero_name}", session["live_prob_a"] or session["assigned_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


def set_time_correction(session: dict, seconds: float) -> dict:
    if session["phase"] != "live":
        raise InvalidActionError("Time can only be corrected during the live phase.")
    session["live"]["time_correction"] = seconds
    _touch(session)
    persistence.save_session(session)
    return session


def end_match(session: dict, team: str) -> dict:
    """team = the side whose ancient fell (i.e. the *loser*)."""
    if session["phase"] != "live":
        raise InvalidActionError("Can only end the match from the live phase.")
    winner = OTHER_TEAM[team]
    if session["live"]["started_at"] is not None and session["live"]["status"] != "paused":
        session["live"]["paused_at"] = time.time()  # freeze the clock's end-point, reusing the paused-time field
    session["live"]["ended"] = True
    session["live"]["status"] = "ended"
    session["live"]["winner"] = winner
    session["live_prob_a"] = MAX_PROB if winner == "team_a" else MIN_PROB
    session["phase"] = "complete"
    _log(session, "complete", f"{session[team]['label']}'s Ancient fell -- {session[winner]['label']} wins", session["live_prob_a"])
    _touch(session)
    persistence.save_session(session)
    return session


# ---------------------------------------------------------------------------
# Read-only views
# ---------------------------------------------------------------------------

def get_dashboard(session: dict) -> dict:
    pipeline = get_pipeline_data()

    def team_view(team: str) -> dict:
        team_id = session[team]["team_id"]
        tendency = pipeline.team_tendencies.get(team_id)
        top_picks = [] if not tendency else [
            {"hero_id": h.hero_id, "hero_name": pipeline.hero_names.get(h.hero_id, f"hero_{h.hero_id}"), "count": h.count, "rate": h.rate}
            for h in tendency.top_picks
        ]
        top_bans = [] if not tendency else [
            {"hero_id": h.hero_id, "hero_name": pipeline.hero_names.get(h.hero_id, f"hero_{h.hero_id}"), "count": h.count, "rate": h.rate}
            for h in tendency.top_bans
        ]
        players = []
        for account_id in session["roster"][team]:
            heroes = top_heroes(account_id, pipeline.affinity, n=5)
            players.append({
                "account_id": account_id,
                "name": display_name(account_id, pipeline.player_names, {}),
                "top_heroes": [
                    {"hero_id": s.hero_id, "hero_name": pipeline.hero_names.get(s.hero_id, f"hero_{s.hero_id}"),
                     "games": s.games, "win_rate": s.win_rate}
                    for s in heroes
                ],
            })
        return {"top_picks": top_picks, "top_bans": top_bans, "players": players}

    return {"patch": pipeline.patch, "team_a": team_view("team_a"), "team_b": team_view("team_b")}


def get_assignment_view(session: dict) -> dict:
    pipeline = get_pipeline_data()

    def team_view(team: str) -> dict:
        drafted = [
            {"hero_id": p["hero_id"], "hero_name": pipeline.hero_names.get(p["hero_id"], f"hero_{p['hero_id']}"),
             "assigned_to": session["assignments"][team].get(str(p["hero_id"]))}
            for p in session["picks"] if p["team"] == team
        ]
        roster = [
            {"account_id": a, "name": display_name(a, pipeline.player_names, {})}
            for a in session["roster"][team]
        ]
        return {"drafted_heroes": drafted, "roster": roster}

    return {"team_a": team_view("team_a"), "team_b": team_view("team_b")}


def get_hero_names() -> dict[int, str]:
    return get_pipeline_data().hero_names


def session_view(session: dict) -> dict:
    """
    Session dict plus derived, non-persisted fields the frontend needs on
    every response (current Captain's Mode step, live elapsed seconds) --
    kept out of the saved JSON so persistence.py's file stays pure state,
    not a mix of state and things recomputed from it.
    """
    view = dict(session)
    view["draft_step"] = current_draft_step(session)
    view["live"] = dict(session["live"])
    view["live"]["elapsed_seconds"] = _compute_elapsed_seconds(session)
    return view


def _compute_elapsed_seconds(session: dict) -> float | None:
    live = session["live"]
    if live["started_at"] is None:
        return None
    end_point = live["paused_at"] if live["status"] in ("paused", "ended") else time.time()
    return (end_point - live["started_at"]) - live["total_paused_seconds"] + live["time_correction"]
