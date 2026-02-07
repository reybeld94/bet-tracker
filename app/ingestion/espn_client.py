"""ESPN HTTP client for fetching scoreboards."""

from __future__ import annotations

import json
import time
from datetime import date
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.ingestion.leagues import get_league_path

BASE_URL = "https://site.web.api.espn.com/apis/v2"
DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 0.5
DEFAULT_USER_AGENT = "bet-tracker/1.0 (+https://example.local)"


def _build_scoreboard_url(league_key: str, game_date: Optional[date]) -> str:
    league_path = get_league_path(league_key)
    if league_path is None:
        raise ValueError(f"Unsupported league key: {league_key}")

    url = f"{BASE_URL}/{league_path}/scoreboard"
    if game_date:
        url = f"{url}?dates={game_date.strftime('%Y%m%d')}"
    return url


def fetch_scoreboard(league_key: str, game_date: Optional[date] = None) -> dict:
    """Fetch ESPN scoreboard data for a league and optional date.

    Returns parsed JSON on success. On failure, returns a controlled error dict.
    """

    try:
        url = _build_scoreboard_url(league_key, game_date)
    except ValueError as exc:
        return {
            "error": str(exc),
            "league": league_key,
            "date": game_date.strftime("%Y%m%d") if game_date else None,
        }

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json",
    }

    last_error: str | None = None
    for attempt in range(DEFAULT_RETRIES):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if attempt < DEFAULT_RETRIES - 1:
                time.sleep(DEFAULT_BACKOFF_SECONDS * (2**attempt))

    return {
        "error": "Failed to fetch ESPN scoreboard",
        "details": last_error,
        "league": league_key,
        "date": game_date.strftime("%Y%m%d") if game_date else None,
        "url": url,
    }
