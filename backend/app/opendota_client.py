#!/usr/bin/env python3
"""
backend/app/opendota_client.py

Purpose:
Provide a small reusable OpenDota API client for fetching pro matches, personal
match history, and full match details while keeping request code centralized.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

import requests


class OpenDotaClient:
    """
    Lightweight API client for OpenDota.

    This wraps a requests.Session so your scripts can share common headers,
    optional API key usage, timeouts, and request helpers.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 30,
        user_agent: str = "dota-website-bot/1.0",
        sleep_seconds: float = 0.0,
        on_successful_request: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Initialize the client.

        Args:
            api_key: Optional OpenDota API key.
            timeout: Request timeout in seconds.
            user_agent: User-Agent header sent with requests.
            sleep_seconds: Optional delay after each successful request.
            on_successful_request: Optional callback run once after each
                successful API request that used the API key. This is useful
                for tracking persistent paid API usage in the database.
        """
        self.base_url = "https://api.opendota.com/api"
        self.api_key = api_key
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        self.on_successful_request = on_successful_request

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
        })

    def _request(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        use_api_key: bool = False,
    ) -> Any:
        """
        Make a GET request to an OpenDota API path and return parsed JSON.

        Args:
            path: API path beginning with a slash, such as '/proMatches'.
            params: Optional query parameter dictionary.
            use_api_key: Whether to include the API key on this request.

        Returns:
            Parsed JSON response content.

        Raises:
            ValueError: If use_api_key=True but no API key is configured.
            requests.HTTPError: If the response is not successful.
            requests.RequestException: For connection, timeout, or other request issues.
        """
        url = f"{self.base_url}{path}"
        final_params = dict(params or {})

        if use_api_key:
            if not self.api_key:
                raise ValueError("use_api_key=True but no API key is configured.")
            final_params["api_key"] = self.api_key

        response = self.session.get(
            url,
            params=final_params or None,
            timeout=self.timeout,
        )
        response.raise_for_status()

        # Only count the request after it succeeded, and only if it used the key.
        if use_api_key and self.on_successful_request is not None:
            self.on_successful_request()

        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)

        return response.json()

    def get_pro_matches(
        self,
        less_than_match_id: Optional[int] = None,
        use_api_key: bool = False,
    ) -> list[dict]:
        """
        Fetch a page of pro matches from /proMatches.

        Args:
            less_than_match_id: Optional pagination value. When provided,
                OpenDota returns matches older than this match ID.
            use_api_key: Whether to include the API key on this request.

        Returns:
            A list of pro match summary dictionaries.
        """
        params: dict[str, Any] = {}
        if less_than_match_id is not None:
            params["less_than_match_id"] = less_than_match_id

        data = self._request(
            "/proMatches",
            params=params or None,
            use_api_key=use_api_key,
        )
        return data if isinstance(data, list) else []

    def get_match(
        self,
        match_id: int,
        use_api_key: bool = False,
    ) -> dict:
        """
        Fetch full detail for a single match from /matches/{match_id}.

        Args:
            match_id: OpenDota match ID.
            use_api_key: Whether to include the API key on this request.

        Returns:
            A dictionary containing the full match payload.
        """
        data = self._request(
            f"/matches/{match_id}",
            use_api_key=use_api_key,
        )
        return data if isinstance(data, dict) else {}

    def get_player_matches(
        self,
        account_id: int,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        lobby_type: Optional[int] = None,
        significant: Optional[int] = None,
        use_api_key: bool = False,
    ) -> list[dict]:
        """
        Fetch match history for a player from /players/{account_id}/matches.

        Args:
            account_id: Steam/OpenDota account ID.
            limit: Optional page size.
            offset: Optional offset for pagination.
            lobby_type: Optional lobby type filter.
            significant: Optional OpenDota significance filter.
            use_api_key: Whether to include the API key on this request.

        Returns:
            A list of match history dictionaries.
        """
        params: dict[str, Any] = {}

        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if lobby_type is not None:
            params["lobby_type"] = lobby_type
        if significant is not None:
            params["significant"] = significant

        data = self._request(
            f"/players/{account_id}/matches",
            params=params or None,
            use_api_key=use_api_key,
        )
        return data if isinstance(data, list) else []

    def close(self) -> None:
        """
        Close the underlying HTTP session.

        This should be called when you are done with the client to release
        network resources cleanly.
        """
        self.session.close()