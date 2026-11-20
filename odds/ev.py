#!/usr/bin/env python3
"""
ev.py

Purpose:
Turn a two-way moneyline (decimal odds on each side) into a devigged fair
probability, compare it against the model's Glicko-2 win probability, and
flag +EV bets. Conservative edge estimate leans on each team's RD (phi)
instead of trusting the point-estimate rating, since a wide-RD team's "edge"
is much less trustworthy than a narrow-RD team's.

Location:
    odds/ev.py
"""

from __future__ import annotations

from dataclasses import dataclass

from . import glicko2
from .series import series_win_probability

# How many rating-deviations to lean against the bet when computing the
# conservative edge: shift the bet-side rating down and the opponent's up by
# this many phi before recomputing win probability.
DEFAULT_CONSERVATISM_Z = 1.0


@dataclass
class DevigResult:
    fair_prob_a: float
    fair_prob_b: float
    overround: float


def american_to_decimal(american_odds: float) -> float:
    """Convert American odds (e.g. +150, -200) to decimal odds."""
    if american_odds > 0:
        return 1.0 + american_odds / 100.0
    return 1.0 + 100.0 / abs(american_odds)


def decimal_to_american(decimal_odds: float) -> float:
    """Convert decimal odds to American odds (e.g. +150, -200)."""
    if decimal_odds >= 2.0:
        return (decimal_odds - 1.0) * 100.0
    return -100.0 / (decimal_odds - 1.0)


def parse_odds(token) -> float:
    """
    Parse one odds value, auto-detecting the format by magnitude, and
    return it as decimal -- the representation every other function in
    this module expects:
      - |value| >= 100                -> American (e.g. -150, +150)
      - 1.0 <= value < 100             -> already decimal (e.g. 1.90)
      - 0 < value < 1.0                -> a prediction-market price
        (Polymarket/Kalshi: a share trading at $0.58, or "58 cents",
        *is* the market's implied probability directly -- no vig-split
        moneyline the way a sportsbook quotes it. Decimal odds are never
        below 1.0 and American odds are never below 100 in magnitude, so
        this range is unambiguous.)

    Accepts '-150', '+150', '150' (American), '1.90' (decimal), or '0.58'
    (prediction-market price), or an already plain int/float.
    """
    value = float(token)
    if abs(value) >= 100:
        return american_to_decimal(value)
    if 0 < value < 1:
        return 1.0 / value
    return value


def format_american(decimal_odds: float) -> str:
    """Decimal odds as an American odds string, e.g. '+150' or '-200'."""
    american = decimal_to_american(decimal_odds)
    return f"+{american:.0f}" if american > 0 else f"{american:.0f}"


def devig_multiplicative(odds_a: float, odds_b: float) -> DevigResult:
    """
    Remove the bookmaker's margin from a two-way moneyline via simple
    multiplicative normalization (each side's implied probability divided by
    the total implied probability). This is an approximation -- it doesn't
    correct for favorite-longshot bias the way Shin's method does -- but it's
    a reasonable default for a two-outcome esports market.

    Args:
        odds_a: Decimal odds on side A (e.g. 1.85).
        odds_b: Decimal odds on side B.

    Returns:
        DevigResult with fair (vig-free) probabilities for both sides and
        the raw overround for reference.
    """
    raw_a = 1.0 / odds_a
    raw_b = 1.0 / odds_b
    overround = raw_a + raw_b
    return DevigResult(fair_prob_a=raw_a / overround, fair_prob_b=raw_b / overround, overround=overround)


def expected_value(prob_win: float, decimal_odds: float, stake: float = 1.0) -> float:
    """EV of a bet, in the same units as `stake`. Positive means +EV."""
    return stake * (prob_win * decimal_odds - 1.0)


def kelly_fraction(prob_win: float, decimal_odds: float) -> float:
    """
    Fraction of bankroll the Kelly criterion would size this bet at.
    Clamped to 0 for -EV bets (Kelly is undefined/negative there).
    """
    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0
    f = (prob_win * decimal_odds - 1.0) / b
    return max(0.0, f)


def conservative_win_probability(
    rating_for: glicko2.Rating,
    rating_against: glicko2.Rating,
    z: float = DEFAULT_CONSERVATISM_Z,
) -> float:
    """
    A pessimistic win probability for the "for" side: shift its rating down
    by z*phi and the opponent's up by z*phi before comparing. This uses each
    team's own uncertainty (RD) rather than the raw point-estimate rating, so
    a newly-formed or long-dormant team's edge gets discounted appropriately.
    """
    shifted_for = glicko2.Rating(
        mu=rating_for.mu - z * rating_for.phi,
        phi=rating_for.phi,
        sigma=rating_for.sigma,
    )
    shifted_against = glicko2.Rating(
        mu=rating_against.mu + z * rating_against.phi,
        phi=rating_against.phi,
        sigma=rating_against.sigma,
    )
    return glicko2.expected_score(shifted_for, shifted_against)


@dataclass
class BetEvaluation:
    team: str
    opponent: str
    decimal_odds: float
    model_prob: float
    fair_market_prob: float
    edge: float  # model_prob - fair_market_prob
    ev: float  # per unit staked
    conservative_prob: float
    conservative_ev: float
    kelly: float
    is_positive_ev: bool  # conservative_ev > 0, the RD-aware flag


def evaluate_moneyline(
    team_a_name: str,
    team_b_name: str,
    odds_a: float,
    odds_b: float,
    rating_a: glicko2.Rating,
    rating_b: glicko2.Rating,
    conservatism_z: float = DEFAULT_CONSERVATISM_Z,
    best_of: int = 3,
) -> list[BetEvaluation]:
    """
    Evaluate both sides of a two-way moneyline against the model.

    Args:
        team_a_name, team_b_name: Display names for the two sides.
        odds_a, odds_b: Decimal odds quoted for each side.
        rating_a, rating_b: Current effective Glicko-2 ratings for each team.
        conservatism_z: How many phi to discount the point-estimate edge by;
            see conservative_win_probability.
        best_of: Series length the *odds* are quoted on (a "Match Winner"
            moneyline is normally a full Bo3/Bo5 series, not one game).
            glicko2.expected_score, which rating_a/rating_b feed into, is a
            per-GAME probability -- pro_matches stores individual games
            (confirmed via series_id grouping 2-6 of them per series), and
            the whole rating pipeline treats each one as one independent
            observation. Comparing a per-game probability directly against
            a per-series market -- which every version of this function
            before this parameter existed did -- understates a favorite's
            true series win probability and overstates an underdog's, more
            so the more lopsided the per-game number already is. Pass
            best_of=1 to skip the conversion (e.g. a market that actually
            is single-game, like a "Map 1 Winner" line).

    Returns:
        A [team_a evaluation, team_b evaluation] list. A bet is flagged
        is_positive_ev only if it clears +EV even under the conservative
        (RD-discounted) probability, not just the raw point estimate.
    """
    devig = devig_multiplicative(odds_a, odds_b)
    game_prob_a = glicko2.expected_score(rating_a, rating_b)
    model_prob_a = series_win_probability(game_prob_a, best_of) if best_of > 1 else game_prob_a
    model_prob_b = 1.0 - model_prob_a

    game_conservative_a = conservative_win_probability(rating_a, rating_b, conservatism_z)
    game_conservative_b = conservative_win_probability(rating_b, rating_a, conservatism_z)
    conservative_a = series_win_probability(game_conservative_a, best_of) if best_of > 1 else game_conservative_a
    conservative_b = series_win_probability(game_conservative_b, best_of) if best_of > 1 else game_conservative_b

    eval_a = BetEvaluation(
        team=team_a_name,
        opponent=team_b_name,
        decimal_odds=odds_a,
        model_prob=model_prob_a,
        fair_market_prob=devig.fair_prob_a,
        edge=model_prob_a - devig.fair_prob_a,
        ev=expected_value(model_prob_a, odds_a),
        conservative_prob=conservative_a,
        conservative_ev=expected_value(conservative_a, odds_a),
        kelly=kelly_fraction(model_prob_a, odds_a),
        is_positive_ev=expected_value(conservative_a, odds_a) > 0,
    )
    eval_b = BetEvaluation(
        team=team_b_name,
        opponent=team_a_name,
        decimal_odds=odds_b,
        model_prob=model_prob_b,
        fair_market_prob=devig.fair_prob_b,
        edge=model_prob_b - devig.fair_prob_b,
        ev=expected_value(model_prob_b, odds_b),
        conservative_prob=conservative_b,
        conservative_ev=expected_value(conservative_b, odds_b),
        kelly=kelly_fraction(model_prob_b, odds_b),
        is_positive_ev=expected_value(conservative_b, odds_b) > 0,
    )
    return [eval_a, eval_b]
