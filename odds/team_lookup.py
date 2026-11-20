#!/usr/bin/env python3
"""
team_lookup.py

Purpose:
Resolve a human-typed team name (from a TI roster list or an odds feed) to
the OpenDota team_id used as the rating key. Names drift across rebrands and
across data sources, so this does exact match first, then a word-prefix
match, then falls back to fuzzy matching rather than requiring perfect
string equality everywhere. Mirrors hero_names.py's resolve_hero design.

Location:
    odds/team_lookup.py
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass
class NameMatch:
    query: str
    matched_name: str | None
    confidence: str  # "exact", "prefix", "fuzzy", "ambiguous", or "unmatched"
    candidates: list[str] | None = None  # populated only when confidence == "ambiguous"


@dataclass
class LookupResult:
    query: str
    team_id: int | None
    matched_name: str | None
    confidence: str  # "exact", "prefix", "fuzzy", "ambiguous", "override", or "unmatched"
    candidates: list[str] | None = None
    # The resolved canonical form of the name, when the caller's matching
    # layer has one distinct from matched_name -- e.g.
    # ti2026_teams.resolve_team_id populates this with the TI2026 roster's
    # canonical name (not the DB's display name) so
    # ti2026_teams.apply_lineup_overrides, which is keyed on that canonical
    # name, can be called correctly even when the user typed an
    # abbreviation. None for lookups with no such distinction.
    canonical: str | None = None


def match_name(query: str, candidate_names: list[str], fuzzy_cutoff: float = 0.75) -> NameMatch:
    """
    Resolve a typed name against a list of candidate display names, trying
    the raw query first and then a "Team " prefix stripped off it (a
    bookmaker writing "Team AURORA" for the org actually named "Aurora
    Gaming" would otherwise fail entirely: the query's own first word
    "Team" isn't part of what makes the candidate match, but the naive
    single-string word-prefix check below has no way to know that "AURORA"
    is the part that matters unless it's tried on its own -- confirmed
    bug, "Team AURORA" fuzzy-matched a real but unrelated "Team ARQA"
    before this fallback existed).

    Returns the first variant that isn't unmatched; an ambiguous result
    from the raw query is still returned immediately (it's a real signal,
    not a failure to retry past).
    """
    for variant in _query_variants(query):
        result = _match_name_single(variant, candidate_names, fuzzy_cutoff)
        if result.confidence != "unmatched":
            return NameMatch(query, result.matched_name, result.confidence, result.candidates)
    return NameMatch(query, None, None, "unmatched")


def _query_variants(query: str) -> list[str]:
    variants = [query]
    stripped = query.strip()
    if stripped.lower().startswith("team "):
        variants.append(stripped[5:])
    return variants


def _match_name_single(query: str, candidate_names: list[str], fuzzy_cutoff: float) -> NameMatch:
    """
    Resolve a typed name against a list of candidate display names.

    Word-prefix matching means the query only needs to be a prefix of *any*
    individual word in a name, not the whole name -- "falcons" or "falc"
    both resolve to "Team Falcons" via its second word, even though several
    other candidates also start with "Team ". If a prefix matches more than
    one candidate, that's reported as ambiguous rather than guessed.

    Args:
        query: Name as typed by the user or seen in an odds feed.
        candidate_names: The display names to match against.
        fuzzy_cutoff: Minimum difflib similarity ratio to accept a fuzzy
            match; below this the name is reported unmatched.

    Returns:
        NameMatch describing the best match found, if any.
    """
    q = query.strip().lower()
    if not q:
        return NameMatch(query, None, "unmatched")

    for name in candidate_names:
        if name.strip().lower() == q:
            return NameMatch(query, name, "exact")

    seen: set[str] = set()
    prefix_matches: list[str] = []
    for name in candidate_names:
        name_lower = name.strip().lower()
        if name_lower in seen:
            continue
        if name_lower.startswith(q) or any(word.startswith(q) for word in name_lower.split()):
            seen.add(name_lower)
            prefix_matches.append(name)

    if len(prefix_matches) == 1:
        return NameMatch(query, prefix_matches[0], "prefix")
    if len(prefix_matches) > 1:
        return NameMatch(query, None, "ambiguous", candidates=sorted(prefix_matches))

    close = difflib.get_close_matches(query, candidate_names, n=1, cutoff=fuzzy_cutoff)
    if close:
        return NameMatch(query, close[0], "fuzzy")

    return NameMatch(query, None, "unmatched")


def find_team_id(query: str, names: dict[int, str], fuzzy_cutoff: float = 0.75) -> LookupResult:
    """
    Resolve one team name against the team_id -> name map.

    Args:
        query: Team name as typed by the user or seen in an odds feed.
        names: team_id -> latest known display name (from
            data.latest_team_names).
        fuzzy_cutoff: Minimum difflib similarity ratio to accept a fuzzy
            match; below this the team is reported unmatched rather than
            guessing.

    Returns:
        LookupResult describing the best match found, if any. Two
        unrelated orgs can end up sharing an identical current display
        name (rebrands aren't coordinated) -- an exact match against more
        than one team_id is reported "ambiguous" with `candidates`
        team_id-qualified, rather than silently picking whichever one
        happens to come first in `names`' iteration order.
    """
    q = query.strip().lower()

    exact_matches = [(team_id, name) for team_id, name in names.items() if name.strip().lower() == q]
    if len(exact_matches) == 1:
        team_id, name = exact_matches[0]
        return LookupResult(query, team_id, name, "exact")
    if len(exact_matches) > 1:
        candidates = [f"{name} (team_id={team_id})" for team_id, name in exact_matches]
        return LookupResult(query, None, None, "ambiguous", candidates=candidates)

    match = match_name(query, list(names.values()), fuzzy_cutoff)
    if match.confidence == "ambiguous":
        return LookupResult(query, None, None, "ambiguous", candidates=match.candidates)
    if match.matched_name is None:
        return LookupResult(query, None, None, "unmatched")

    for team_id, name in names.items():
        if name == match.matched_name:
            return LookupResult(query, team_id, name, match.confidence)
    return LookupResult(query, None, None, "unmatched")


def find_team_ids(queries: list[str], names: dict[int, str], fuzzy_cutoff: float = 0.75) -> list[LookupResult]:
    """Resolve a batch of team names. See find_team_id for details."""
    return [find_team_id(q, names, fuzzy_cutoff) for q in queries]
