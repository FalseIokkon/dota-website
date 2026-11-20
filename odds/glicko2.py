#!/usr/bin/env python3
"""
glicko2.py

Purpose:
Standalone Glicko-2 rating algorithm (Glickman, "Example of the Glicko-2
system", 2013). No DB or project dependencies here on purpose -- this module
only knows about ratings, deviations, volatilities, and game outcomes, so it
can be tested and reused independently of how matches are stored.

Ratings are tracked on the internal Glicko-2 scale (mu, phi) plus the
volatility sigma. `Rating.value`/`Rating.rd` convert to the familiar
1500-centered display scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Hashable

# Glicko-2 scale conversion constant
_SCALE = 173.7178

DEFAULT_RATING = 1500.0
DEFAULT_RD = 350.0
DEFAULT_VOLATILITY = 0.06

# System constant controlling how much volatility can change per period.
# Glickman suggests picking a value between 0.3 and 1.2 based on the
# expected volatility of ratings in the population; 0.5 is a common default.
DEFAULT_TAU = 0.5

_EPSILON = 1e-6


@dataclass
class Rating:
    """A team's rating state on the internal Glicko-2 scale."""

    mu: float = 0.0
    phi: float = DEFAULT_RD / _SCALE
    sigma: float = DEFAULT_VOLATILITY

    @classmethod
    def from_display(
        cls,
        rating: float = DEFAULT_RATING,
        rd: float = DEFAULT_RD,
        sigma: float = DEFAULT_VOLATILITY,
    ) -> "Rating":
        """Build a Rating from display-scale (1500-centered) values."""
        return cls(mu=(rating - DEFAULT_RATING) / _SCALE, phi=rd / _SCALE, sigma=sigma)

    @property
    def value(self) -> float:
        """Display-scale rating (centered on 1500)."""
        return self.mu * _SCALE + DEFAULT_RATING

    @property
    def rd(self) -> float:
        """Display-scale rating deviation."""
        return self.phi * _SCALE

    def with_inactivity(self, periods_skipped: int) -> "Rating":
        """
        Return the rating after `periods_skipped` rating periods with no games.

        Only phi (uncertainty) grows during inactivity; mu and sigma are
        unchanged. Because sigma is constant across empty periods, the
        repeated-application formula collapses to a closed form:
        phi_k^2 = phi_0^2 + k * sigma^2.
        """
        if periods_skipped <= 0:
            return self
        new_phi = math.sqrt(self.phi**2 + periods_skipped * self.sigma**2)
        return Rating(mu=self.mu, phi=new_phi, sigma=self.sigma)


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi**2 / math.pi**2)


def _E(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def expected_score(rating: Rating, opponent: Rating) -> float:
    """
    Probability that `rating` beats `opponent`, using the standard two-player
    Glicko comparison: combine both sides' uncertainty via g(sqrt(phi_a^2+phi_b^2)).
    """
    combined_phi = math.sqrt(rating.phi**2 + opponent.phi**2)
    return 1.0 / (1.0 + math.exp(-_g(combined_phi) * (rating.mu - opponent.mu)))


def _solve_volatility(phi: float, sigma: float, v: float, delta: float, tau: float) -> float:
    """
    Illinois-algorithm root find for the new volatility (Glickman step 5).
    """
    a = math.log(sigma**2)

    def f(x: float) -> float:
        ex = math.exp(x)
        num = ex * (delta**2 - phi**2 - v - ex)
        den = 2.0 * (phi**2 + v + ex) ** 2
        return num / den - (x - a) / (tau**2)

    A = a
    if delta**2 > phi**2 + v:
        B = math.log(delta**2 - phi**2 - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        B = a - k * tau

    fA = f(A)
    fB = f(B)

    while abs(B - A) > _EPSILON:
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB < 0:
            A, fA = B, fB
        else:
            fA = fA / 2.0
        B, fB = C, fC

    return math.exp(A / 2.0)


def update_rating(
    rating: Rating,
    opponents: list[tuple[Rating, float]],
    tau: float = DEFAULT_TAU,
) -> Rating:
    """
    Apply one rating-period update.

    Args:
        rating: The team's pre-period rating state.
        opponents: List of (opponent_pre_period_rating, score) for every game
            the team played this period. score is 1.0 for a win, 0.0 for a
            loss (Dota has no draws).
        tau: System volatility-change constant.

    Returns:
        The team's post-period Rating. If `opponents` is empty, only phi
        grows (equivalent to one period of inactivity).
    """
    if not opponents:
        return rating.with_inactivity(1)

    v_inv = 0.0
    delta_sum = 0.0
    for opp, score in opponents:
        g_phi_j = _g(opp.phi)
        e = _E(rating.mu, opp.mu, opp.phi)
        v_inv += (g_phi_j**2) * e * (1.0 - e)
        delta_sum += g_phi_j * (score - e)

    v = 1.0 / v_inv
    delta = v * delta_sum

    new_sigma = _solve_volatility(rating.phi, rating.sigma, v, delta, tau)

    phi_star = math.sqrt(rating.phi**2 + new_sigma**2)
    new_phi = 1.0 / math.sqrt(1.0 / phi_star**2 + 1.0 / v)
    new_mu = rating.mu + new_phi**2 * delta_sum

    return Rating(mu=new_mu, phi=new_phi, sigma=new_sigma)


def batch_update(
    pre_period: dict[Hashable, Rating],
    opponents: dict[Hashable, list[tuple[Rating, float]]],
    tau: float = DEFAULT_TAU,
) -> dict[Hashable, Rating]:
    """
    Apply one rating-period update to every entity that played at least one
    game this period. Shared by the team-level and player-level pipelines
    (odds/ratings.py, odds/player_ratings.py) so the period-batch update
    loop only exists once.

    Args:
        pre_period: entity_id -> its rating entering this period.
        opponents: entity_id -> list of (opponent_pre_period_rating, score)
            for every game it played this period.
        tau: Glicko-2 system volatility-change constant.

    Returns:
        entity_id -> its post-period rating, for every key in `opponents`.
        Entities with no games this period aren't included here -- callers
        handle their inactivity decay separately via Rating.with_inactivity.
    """
    return {
        entity_id: update_rating(pre_period[entity_id], games, tau=tau)
        for entity_id, games in opponents.items()
    }
