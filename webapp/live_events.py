#!/usr/bin/env python3
"""
live_events.py

Purpose:
Heuristic win-probability adjustments for live in-game events (kills,
towers, barracks, Roshan, Tormentor, gold lead). Styled deliberately like
odds/hero_adjustment.py's own disclaimed constants (ADJUSTMENT_SCALE,
BAN_PRESSURE_WEIGHT): every weight below is an illustrative starting point,
not backtested against real live win-probability curves -- there is no
data in this repo to calibrate them against (that would need timestamped
gold/kill/objective logs per match, which nothing here scrapes). Treat the
live-tracker probability as directional, same caveat live_draft.py already
carries for its own hero-fit adjustment.

Two different composition rules are used on purpose, kept separate rather
than folded into one running total, so the breakdown stays inspectable
(see webapp/draft_engine.py's LiveState):

- Discrete events (kill/tower/barracks/roshan/tormentor) are cumulative --
  each one contributes a signed delta that adds to a running total.
- Gold lead and the manual nudge are snapshots -- each update is an
  absolute value that *replaces* the previous one, not a delta that stacks.
  A gold lead of +5000 five minutes ago and +200 now should not still be
  contributing the +5000 shift; only the current value should.

Location:
    webapp/live_events.py
"""

from __future__ import annotations

from dataclasses import dataclass

from odds.hero_adjustment import MAX_PROB, MIN_PROB

# Per-tower probability-point swing, by tier, credited to the team that did
# NOT own the tower. Later tiers guard more (higher ground, base proximity)
# so they're worth more than tier 1s, which fall in nearly every game.
TOWER_WEIGHTS: dict[int, float] = {
    1: 0.015,
    2: 0.020,
    3: 0.030,
    4: 0.020,
}

# Barracks are a stronger signal than any single tower (megacreeps), but
# melee racks matter more than ranged -- melee megacreeps are the ones that
# actually threaten a base on their own.
BARRACKS_WEIGHTS: dict[str, float] = {
    "melee": 0.035,
    "ranged": 0.020,
}

ROSHAN_WEIGHT = 0.035
TORMENTOR_WEIGHT = 0.015
KILL_WEIGHT = 0.010

# Buyback has no default probability weight -- it's tracked as a state/
# timeline marker only (see draft_engine.LiveState.buybacks), not folded
# into the number. Left as a named constant so a future revision can add
# one without touching the event-application plumbing.
BUYBACK_WEIGHT = 0.0

# Gold lead -> probability-point curve: capped-linear, GOLD_LEAD_SCALE
# probability points per 1000 gold of lead, capped at +-MAX_GOLD_LEAD_PP so
# a snowballing 30k gold lead doesn't single-handedly blow past what the
# discrete objective events already imply.
GOLD_LEAD_SCALE = 0.01  # pp per 1000 gold
MAX_GOLD_LEAD_PP = 0.20


@dataclass
class LiveEvent:
    event_type: str  # "kill" | "building" | "roshan" | "tormentor"
    credited_team: str  # "team_a" | "team_b"
    building_type: str | None = None  # "tower" | "barracks", when event_type == "building"
    tier: int | None = None  # tower tier 1-4
    lane: str | None = None  # "top" | "mid" | "bot", informational only
    rax_type: str | None = None  # "melee" | "ranged", when building_type == "barracks"
    hero_id: int | None = None  # who got credit, when known (roshan/tormentor/kill)
    objective_id: str | None = None  # frontend map_data.js id, for idempotency/undo/reload state only


def event_weight(event: LiveEvent) -> float:
    """
    Unsigned magnitude of a single discrete event's probability-point
    contribution. The caller (draft_engine.record_live_event) applies the
    sign based on which team is credited.
    """
    if event.event_type == "kill":
        return KILL_WEIGHT
    if event.event_type == "roshan":
        return ROSHAN_WEIGHT
    if event.event_type == "tormentor":
        return TORMENTOR_WEIGHT
    if event.event_type == "building":
        if event.building_type == "tower":
            return TOWER_WEIGHTS.get(event.tier or 1, 0.0)
        if event.building_type == "barracks":
            return BARRACKS_WEIGHTS.get(event.rax_type or "ranged", 0.0)
    return 0.0


def signed_delta(event: LiveEvent, team_a: str = "team_a") -> float:
    """Positive if the event favors team_a, negative if it favors team_b."""
    magnitude = event_weight(event)
    return magnitude if event.credited_team == team_a else -magnitude


def gold_lead_to_prob(gold_lead: float) -> float:
    """
    Convert a snapshot gold-lead value (positive = team_a ahead) into a
    probability-point contribution, capped-linear. See module docstring.
    """
    pp = (gold_lead / 1000.0) * GOLD_LEAD_SCALE
    return max(-MAX_GOLD_LEAD_PP, min(MAX_GOLD_LEAD_PP, pp))


def apply_event_weight(prob_a: float, signed_pp: float) -> float:
    """Apply a signed probability-point delta, clamped to hero_adjustment's own [MIN_PROB, MAX_PROB]."""
    return min(max(prob_a + signed_pp, MIN_PROB), MAX_PROB)


def compute_live_prob_a(
    assigned_prob_a: float,
    events: list[LiveEvent],
    gold_lead: float,
    manual_nudge_pp: float,
) -> float:
    """
    Compose the full live-stage probability: the post-draft/post-assignment
    anchor, plus the sum of every discrete event so far, plus the *current*
    gold-lead snapshot, plus the *current* manual nudge -- clamped once at
    the end, not per-term, so intermediate over/undershoot in one term can
    still be pulled back by another rather than getting clipped early.
    """
    event_total = sum(signed_delta(e) for e in events)
    total = assigned_prob_a + event_total + gold_lead_to_prob(gold_lead) + manual_nudge_pp
    return min(max(total, MIN_PROB), MAX_PROB)


def compute_live_breakdown(events: list[LiveEvent], gold_lead: float, manual_nudge_pp: float) -> dict:
    """
    The individual terms behind compute_live_prob_a, so the frontend can
    show them side by side (same "show the pieces, not just the final
    number" spirit as odds/live_draft.py's own status printout) without
    duplicating the gold-lead curve or event-weight table in JS.
    """
    return {
        "event_total_pp": sum(signed_delta(e) for e in events),
        "gold_contribution_pp": gold_lead_to_prob(gold_lead),
        "manual_nudge_pp": manual_nudge_pp,
    }
