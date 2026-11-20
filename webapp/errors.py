#!/usr/bin/env python3
"""
errors.py

Purpose:
Typed errors raised by draft_engine.py, carrying enough structure (match
confidence, ambiguous-name candidates) for app.py's error handler to
serialize a useful JSON 4xx body instead of a generic 500 -- mirrors the
LookupResult/HeroLookupResult "ambiguous, here are the candidates" shape
odds/team_lookup.py and odds/hero_names.py already use for the same
situation in the CLI tool.

Location:
    webapp/errors.py
"""

from __future__ import annotations


class DraftEngineError(Exception):
    """Base class for errors app.py's handler knows how to serialize."""
    status_code = 400

    def __init__(self, message: str, candidates: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.candidates = candidates

    def to_dict(self) -> dict:
        body = {"error": self.message}
        if self.candidates:
            body["candidates"] = self.candidates
        return body


class TeamResolutionError(DraftEngineError):
    """A team name query didn't resolve to exactly one rated team."""


class HeroResolutionError(DraftEngineError):
    """A hero name query didn't resolve to exactly one hero."""


class InvalidActionError(DraftEngineError):
    """The requested action doesn't make sense for the session's current phase/state."""


class SessionNotFoundError(DraftEngineError):
    status_code = 404
