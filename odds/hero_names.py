#!/usr/bin/env python3
"""
hero_names.py

Purpose:
Resolve a human-typed hero name (from live draft input, or for display) to
its OpenDota hero_id, the key used everywhere else in this project
(lineups.csv, matches.payload_json). Hero constants come from
odota/dotaconstants on GitHub -- the static JSON file OpenDota itself builds
from -- so this is a plain one-time file download, not a rate-limited API
(unlike Liquipedia, which temporarily blocked this project's IP earlier for
exceeding its API terms; avoid repeating that mistake elsewhere).

Location:
    odds/hero_names.py
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

import requests

HEROES_URL = "https://raw.githubusercontent.com/odota/dotaconstants/master/build/heroes.json"
CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "derived" / "hero_names.json"

# Common competitive-scene abbreviations, checked before fuzzy matching --
# typing "pa" during a live draft is much faster than "Phantom Assassin".
# Best-effort, not exhaustive; extend as needed.
COMMON_ALIASES: dict[str, str] = {
    "am": "Anti-Mage",
    "pa": "Phantom Assassin",
    "pl": "Phantom Lancer",
    "sf": "Shadow Fiend",
    "sk": "Sand King",
    "sd": "Shadow Demon",
    "cm": "Crystal Maiden",
    "np": "Nature's Prophet",
    "wk": "Wraith King",
    "dp": "Death Prophet",
    "ta": "Templar Assassin",
    "tb": "Terrorblade",
    "ck": "Chaos Knight",
    "es": "Earthshaker",
    "ns": "Night Stalker",
    "qop": "Queen of Pain",
    "kotl": "Keeper of the Light",
    "ck9": "Chaos Knight",
    "od": "Outworld Destroyer",
    "lc": "Legion Commander",
    "ds": "Doom",
    "dk": "Dragon Knight",
    "ww": "Winter Wyvern",
    "brew": "Brewmaster",
    "veno": "Venomancer",
    "furion": "Nature's Prophet",
    "morph": "Morphling",
    "mag": "Magnus",
    "void": "Faceless Void",
    "bs": "Bloodseeker",
    "ck2": "Chaos Knight",
    "clock": "Clockwerk",
    "husk": "Huskar",
    "naga": "Naga Siren",
    "ol": "Outworld Destroyer",
    "rubick": "Rubick",
    "sven": "Sven",
    "tide": "Tidehunter",
    "ur": "Ursa",
    "viper": "Viper",
    "wisp": "Io",
    "zeus": "Zeus",
}


@dataclass
class HeroLookupResult:
    query: str
    hero_id: int | None
    matched_name: str | None
    confidence: str  # "alias", "exact", "prefix", "fuzzy", "ambiguous", or "unmatched"
    candidates: list[str] | None = None  # populated only when confidence == "ambiguous"


def _fetch_and_cache() -> dict[str, str]:
    """Download dotaconstants heroes.json and cache hero_id -> localized_name."""
    resp = requests.get(HEROES_URL, timeout=15)
    resp.raise_for_status()
    raw = resp.json()

    names = {hero_id: entry["localized_name"] for hero_id, entry in raw.items()}

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w") as f:
        json.dump(names, f, indent=2)

    return names


def load_hero_names() -> dict[int, str]:
    """
    Load hero_id -> localized_name, fetching and caching from dotaconstants
    on first use. Cached locally so the live draft tool never needs network
    access mid-draft.

    Returns:
        Mapping of int hero_id to its display name (e.g. "Anti-Mage").
    """
    if CACHE_PATH.exists():
        with CACHE_PATH.open() as f:
            raw = json.load(f)
    else:
        raw = _fetch_and_cache()

    return {int(hero_id): name for hero_id, name in raw.items()}


def resolve_hero(query: str, names: dict[int, str], fuzzy_cutoff: float = 0.7) -> HeroLookupResult:
    """
    Resolve a typed hero name/abbreviation to a hero_id. Checks
    COMMON_ALIASES, then exact match, then a unique-prefix match (e.g. "pri"
    for "Primal Beast" -- fast to type live, since it only resolves when
    exactly one hero's name starts with it), then falls back to fuzzy
    matching for typos. Mirrors team_lookup.find_team_id's design.

    Args:
        query: Hero name or abbreviation as typed by the user.
        names: hero_id -> localized_name (from load_hero_names).
        fuzzy_cutoff: Minimum difflib similarity ratio to accept a fuzzy
            match; below this the hero is reported unmatched rather than
            guessing.

    Returns:
        HeroLookupResult describing the best match found. If the prefix
        matches more than one hero, confidence is "ambiguous" and
        `candidates` lists them -- type more letters rather than guessing.
    """
    q = query.strip().lower()
    if not q:
        return HeroLookupResult(query, None, None, "unmatched")

    if q in COMMON_ALIASES:
        alias_name = COMMON_ALIASES[q]
        for hero_id, name in names.items():
            if name == alias_name:
                return HeroLookupResult(query, hero_id, name, "alias")

    for hero_id, name in names.items():
        if name.strip().lower() == q:
            return HeroLookupResult(query, hero_id, name, "exact")

    prefix_matches = [(hero_id, name) for hero_id, name in names.items() if name.strip().lower().startswith(q)]
    if len(prefix_matches) == 1:
        hero_id, name = prefix_matches[0]
        return HeroLookupResult(query, hero_id, name, "prefix")
    if len(prefix_matches) > 1:
        candidate_names = sorted(name for _, name in prefix_matches)
        return HeroLookupResult(query, None, None, "ambiguous", candidates=candidate_names)

    candidates = {name: hero_id for hero_id, name in names.items()}
    close = difflib.get_close_matches(query, candidates.keys(), n=1, cutoff=fuzzy_cutoff)
    if close:
        matched_name = close[0]
        return HeroLookupResult(query, candidates[matched_name], matched_name, "fuzzy")

    return HeroLookupResult(query, None, None, "unmatched")
