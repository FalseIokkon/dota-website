#!/usr/bin/env python3
"""
ti2026_teams.py

Purpose:
The International 2026's 16-team main-event roster, pulled from Liquipedia
(https://liquipedia.net/dota2/The_International/2026) via the MediaWiki API
on 2026-08-10. Invites were announced 2026-05-25; regional-qualifier slots
were decided after.

Several of these teams don't cleanly resolve to a single pro_matches team_id
by name -- see TI2026_TEAM_ID_OVERRIDES below and the ROSTER_NOTES for why.
Dota orgs rebrand and reshuffle rosters constantly, and OpenDota's team_id
is assigned per registered team page, not per roster, so a roster move to a
new org (or even a re-registered team page for the same org) can silently
orphan the rating history that actually reflects the players competing.

Location:
    odds/ti2026_teams.py
"""

TI2026_TEAMS: list[str] = [
    "Aurora Gaming",
    "BetBoom Team",
    "Iron Wing TI 2026",  # see override below -- roster is ex-Tundra Esports
    "Team Falcons",
    "Team Liquid",
    "Team Yandex",
    "Xtreme Gaming",
    "Team Spirit",
    "TEAM VISION",  # rebrand of PARIVISION / PVISION -- same team_id in DB
    "Nigma Galaxy",  # see override below -- ambiguous team_id, verify
    "HULIGANI",
    "Team Resilience",  # see override below -- ambiguous team_id, verify
    "Vici Gaming",
    "OG",
    "GamerLegion",
    "LGD Gaming",  # roster change 2026-08-09/10, see ROSTER_NOTES
]

# Short codes seen on bracket/broadcast overlays that aren't a literal
# prefix of the team's own name (e.g. "NGX" for Nigma Galaxy has no letters
# in common with a simple prefix match), so they can't be resolved by
# team_lookup.match_name's prefix tier alone. Checked before that tier;
# mirrors hero_names.py's COMMON_ALIASES. Extend as new broadcast codes
# come up -- keys are matched case-insensitively.
TI2026_ALIASES: dict[str, str] = {
    "ngx": "Nigma Galaxy",
    "bb": "BetBoom Team",
    "tr": "Team Resilience",
    "xg": "Xtreme Gaming",
    "vg": "Vici Gaming",
    "gl": "GamerLegion",
    # "iw" is short enough that, without this, it falls through the TI2026
    # canonical list entirely (no word in "Iron Wing TI 2026" starts with
    # "iw") to the *full* pro_matches name space, where it silently
    # prefix-matched a real but totally unrelated team called "Team IW"
    # (team_id=9800464) -- confirmed by testing, not hypothetical.
    "iw": "Iron Wing TI 2026",
    # "BoomBoys" is BetBoom Team's current name (see TI2026_TEAM_ID_OVERRIDES
    # below) -- but pro_matches also has a second, unrelated team_id that
    # briefly used the identical display name (6 games, 2026-Jun), so typing
    # "boomboys" directly would otherwise hit a genuine ambiguous-name
    # collision (team_lookup.find_team_id reports it as such, doesn't
    # guess). Routing it through the canonical name here goes straight to
    # the override instead.
    "boomboys": "BetBoom Team",
    "bb team": "BetBoom Team",

    # TEAM VISION's own former names (PARIVISION -> PVISION -> TEAM VISION,
    # all one continuous team_id 9572001). Bookmakers keep using the old
    # name after a rebrand -- but pro_matches ALSO has a second, unrelated
    # team_id whose *current* latest name happens to be exactly "Parivision"
    # (1 game, 2026-Feb), so a plain lookup silently resolves to that wrong,
    # irrelevant team instead of TEAM VISION (confirmed by testing, not
    # hypothetical -- this bit us on a real bookmaker's odds board).
    "parivision": "TEAM VISION",
    "pvision": "TEAM VISION",

    # HULIGANI's own former name ("L1GA TEAM", 494 games under that name
    # alone -- see TI2026_ADDITIONAL_TEAM_IDS). A bookmaker labeled this
    # matchup "L1ga".
    "l1ga": "HULIGANI",

    # A bookmaker labeled Team Yandex's sponsor/brand as "Yandex.Money"
    # (a real Yandex product name) instead of the team name -- doesn't
    # share a word with "Team Yandex" at all, so no prefix tier catches it.
    "yandex.money": "Team Yandex",
}

# Manual team_id overrides for TI2026 names that don't resolve (or resolve
# ambiguously) against pro_matches via team_lookup.find_team_id's fuzzy name
# matching. Re-verify these periodically -- OpenDota may assign a proper
# team_id to a renamed org later, at which point its override can be removed.
TI2026_TEAM_ID_OVERRIDES: dict[str, int] = {
    # Rebranded BetBoom Team -> BB / BB Team -> BoomBoys (current name in
    # pro_matches). find_team_id only knows a team_id's *latest* name, so
    # "BetBoom Team" doesn't fuzzy-match "BoomBoys" closely enough to resolve
    # automatically.
    "BetBoom Team": 8255888,  # = "BoomBoys" (latest name) in pro_matches

    # Tundra Esports' entire roster transferred to 1win Team, competing here
    # as "Iron Wing TI 2026" (per Liquipedia's roster-move notes). No match
    # history exists yet under "Iron Wing" or "1win Team" in pro_matches, so
    # this rates them using the old Tundra Esports team_id -- same players,
    # different org label -- until OpenDota creates a dedicated team_id.
    "Iron Wing TI 2026": 8291895,  # = "Tundra Esports", 472 games in pro_matches

    # Two Nigma Galaxy team_ids exist in pro_matches (7554697: 385 games,
    # older; 10136357: 57 games, more recent). Confirmed via OpenDota's
    # curated player names (player_names.py) -- 10136357's lineup resolves
    # to SumaiL-, OmaR, Davai, lorenof, GH: an exact 5/5 match against
    # Liquipedia's roster. 7554697 only matches 3/5 (OmaR, Davai, GH; the
    # other two resolve to unrelated players) and is not this roster.
    "Nigma Galaxy": 10136357,

    # Multiple Team Resilience team_ids exist; 5017210 is the one that
    # played the actual TI2026 China regional qualifier that earned this
    # invite. See TI2026_ADDITIONAL_TEAM_IDS -- 10207984 and 9316703 are
    # confirmed the identical simultaneous roster under different
    # registrations, not rival candidates to choose between.
    "Team Resilience": 5017210,

    # Two team_ids are both currently named exactly "Xtreme Gaming" in
    # pro_matches (confirmed identical 5-player roster on both -- not an
    # unrelated-team collision like the BoomBoys one below). Without this
    # override, find_team_id correctly refuses to guess between them
    # (reports "ambiguous") rather than silently picking one, which is what
    # was happening implicitly before this was added. 8261500 has the vast
    # majority of the history (451 games vs. 7); see TI2026_ADDITIONAL_TEAM_IDS.
    "Xtreme Gaming": 8261500,
}

# Teams whose current roster's games are split across more than one
# pro_matches team_id -- confirmed by checking that the *exact same 5
# account_ids* played together (same match, same time) under each id, not
# just that individual players' careers ever overlapped (which happens
# naturally from ordinary roster turnover and proves nothing -- see the
# Nigma Galaxy rejection above). This pattern is real and widespread: orgs
# sponsored by betting companies (BetBoom -> BoomBoys, Tundra -> 1win Team)
# rename to comply with a given tournament's no-gambling-sponsor rules, and
# OpenDota assigns a fresh team_id per registered name rather than treating
# it as the same org -- so the *same players* end up fragmented across
# several ids. Used only to correct the "games" activity count
# (compute_ratings.py) and to widen verify_lineups.py's stability check;
# `current_lineup_by_team` already resolves to the right players either way
# since, by definition of this list, every id here reports an identical
# roster to the primary one.
#
# This audit isn't exhaustive -- it only checked the 16 current TI2026
# rosters against team_ids sharing >=4/5 players. The 5/5-simultaneous
# cases (name changes with the literal same 5 players active at the same
# time -- gambling-sponsor-compliance renames) are listed first below.
#
# A few teams also turned up a 4/5 match: one roster slot differs, so it's
# not a same-moment rename, it's a predecessor org from before a single
# transfer. These were checked individually (via player_names.py) rather
# than assumed real, since a 4/5 overlap can also just be a one-off
# stand-in appearance -- e.g. BetBoom's "BB Team" (28 games) was excluded
# because its differing player is "Pure", who's on a *different* TI2026
# roster (Iron Wing) entirely, making a guest appearance far more likely
# than shared lineage. The three below survived that check: each has a
# large, sustained game count (60-377 games) that's implausible for a
# stand-in, and represents real multi-hundred-game history for 4 of the
# current 5 players that the "games" count would otherwise miss entirely.
TI2026_ADDITIONAL_TEAM_IDS: dict[str, list[int]] = {
    "Iron Wing TI 2026": [10150413, 10182357],  # "Tundra Esports" + "1w" (1win Team branding)
    "TEAM VISION": [9824702],  # "PVISION" / "PARIVISION"
    "HULIGANI": [10208009, 9303383],  # "L1GA TEAM" (9303383 alone has 494 games -- more than the "primary" id)
    "Team Resilience": [10207984, 9316703],
    "Xtreme Gaming": [10208071],
    "OG": [9885654],  # "Team Aureus", 60 games, predecessor SEA org (1 differing player: Nikko)
    "GamerLegion": [9381678, 9651185],  # "Apex Genesis" (2 games) -> "Wildcard" (210 games); differing player: Yamsun
    "LGD Gaming": [10208068, 9303484],  # "LGD.Pinghu" (11) + "HEROIC" (377); differing player: TaiLung (pre-ban)
}


def all_team_ids_for(canonical_name: str, primary_team_id: int) -> list[int]:
    """All team_ids known to represent this roster's games (see TI2026_ADDITIONAL_TEAM_IDS)."""
    return [primary_team_id] + TI2026_ADDITIONAL_TEAM_IDS.get(canonical_name, [])

ROSTER_NOTES = """
- Iron Wing TI 2026: full roster (Pure, bzm, 33, Ari, Whitemon; coach
  MoonMeander) transferred from Tundra Esports to 1win Team, competing under
  this event-specific name. See TI2026_TEAM_ID_OVERRIDES.
- LGD Gaming: TaiLung was permanently banned from the tournament and all
  future PGL events on 2026-08-09 (tournament integrity issue); Topson
  joined the roster 2026-08-10. The org-level rating history predates this
  swap and still reflects TaiLung's games. For the player-composite model,
  see TI2026_LINEUP_OVERRIDES.
"""

# Manual per-player lineup patches for personnel changes too recent for any
# match data to exist yet. player_ratings.PlayerPipelineResult's
# current_lineup_by_team only knows about lineups that have actually played
# a logged match -- a swap announced yesterday won't show up there until
# that player's first match for the team gets scraped. Both account_ids
# below were confirmed against Liquipedia's player infoboxes (playerid=),
# not personaname matching, which is unreliable (many unrelated accounts
# reuse pro players' handles as their Steam display name).
TI2026_LINEUP_OVERRIDES: dict[str, dict[int, int]] = {
    "LGD Gaming": {
        1026694469: 94054712,  # TaiLung (banned 2026-08-09) -> Topson (joined 2026-08-10)
    },
}


def apply_lineup_overrides(team_name: str, account_ids: list) -> list:
    """
    Patch a team's detected current lineup with any manual personnel swaps
    from TI2026_LINEUP_OVERRIDES. account_ids not mentioned in the override
    pass through unchanged.

    Args:
        team_name: A name from TI2026_TEAMS.
        account_ids: The 5 account_ids from
            PlayerPipelineResult.current_lineup_by_team[team_id].

    Returns:
        The patched account_id list, same length and order as the input.
    """
    overrides = TI2026_LINEUP_OVERRIDES.get(team_name)
    if not overrides:
        return account_ids
    return [overrides.get(a, a) for a in account_ids]


def resolve_team_id(name: str, names: dict[int, str]):
    """
    Resolve a TI2026 roster name to a pro_matches team_id.

    First matches against the curated 16-team TI2026_TEAMS list itself
    (exact, then word-prefix, then fuzzy) rather than going straight to the
    full DB name space -- this is what lets short input like "falcons" or
    "falc" resolve unambiguously to "Team Falcons" even though several
    other entries also start with "Team ", and it's what lets abbreviated
    input work at all for teams with an override below (e.g. "iron" needs
    to resolve to the canonical "Iron Wing TI 2026" key before the override
    dict can be checked). Falls back to matching the raw input against the
    DB directly for non-TI2026 opponents (e.g. an arbitrary odds-sheet
    matchup against a team that isn't in this tournament).

    Args:
        name: A name from TI2026_TEAMS, an abbreviation/prefix of one, or
            any other team name known to pro_matches.
        names: team_id -> latest known display name (from
            data.latest_team_names).

    Returns:
        A team_lookup.LookupResult. Overridden lookups report confidence
        "override"; an ambiguous prefix (matching multiple TI2026 teams or
        multiple DB teams) reports "ambiguous" with `candidates` populated.
    """
    from .team_lookup import LookupResult, find_team_id, match_name

    alias_target = TI2026_ALIASES.get(name.strip().lower())
    canonical_match = match_name(alias_target or name, TI2026_TEAMS)
    if canonical_match.confidence == "ambiguous":
        return LookupResult(name, None, None, "ambiguous", candidates=canonical_match.candidates)

    canonical_name = canonical_match.matched_name
    # An alias is a deliberate, curated mapping -- report it as such even
    # though the subsequent match against TI2026_TEAMS will itself say
    # "exact" (it's matching the alias's target string, not the user's
    # original input).
    approx_confidence = "alias" if alias_target else canonical_match.confidence

    if canonical_name is not None and canonical_name in TI2026_TEAM_ID_OVERRIDES:
        team_id = TI2026_TEAM_ID_OVERRIDES[canonical_name]
        return LookupResult(name, team_id, names.get(team_id), "override", canonical=canonical_name)

    result = find_team_id(canonical_name or name, names)
    result.canonical = canonical_name
    # canonical_name now equals a real DB name almost by construction, so
    # find_team_id above typically reports "exact" even when reaching that
    # canonical name in the first place required an alias/prefix/fuzzy
    # guess -- surface the approximate match instead of masking it. Only
    # applies when we actually resolved a TI2026 canonical name in the
    # first place (canonical_name is not None); otherwise this fell
    # through to a plain DB-wide match (e.g. a non-TI2026 opponent) and
    # find_team_id's own confidence is already correct as-is.
    if canonical_name is not None and approx_confidence != "exact" and result.confidence == "exact":
        result.confidence = approx_confidence
    return result
