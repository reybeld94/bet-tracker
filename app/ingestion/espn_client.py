"""ESPN HTTP client for fetching scoreboards."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.ingestion.leagues import get_league_path

logger = logging.getLogger(__name__)
ESPN_BASE_URL = os.getenv("ESPN_BASE_URL", "https://site.api.espn.com").rstrip("/")
SCOREBOARD_BASE_PATH = "/apis/site/v2/sports"
DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 0.5
DEFAULT_USER_AGENT = "bet-tracker/1.0 (+https://example.local)"


def normalize_dates(value: str | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.lower() == "today":
        return date.today().strftime("%Y%m%d")
    if re.fullmatch(r"\d{8}", cleaned):
        return cleaned
    if re.fullmatch(r"\d{8}-\d{8}", cleaned):
        return cleaned
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned.replace("-", "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}", cleaned):
        parts = cleaned.split("-")
        start = "".join(parts[:3])
        end = "".join(parts[3:])
        return f"{start}-{end}"
    raise ValueError("dates must be YYYYMMDD or YYYYMMDD-YYYYMMDD")


def build_scoreboard_url(
    sport: str,
    league: str,
    dates: str | date | None = None,
    extra_params: dict[str, str] | None = None,
) -> str:
    normalized_dates = normalize_dates(dates)
    base_url = (
        f"{ESPN_BASE_URL}{SCOREBOARD_BASE_PATH}/{sport}/{league}/scoreboard"
    )
    params: dict[str, str] = {}
    if normalized_dates:
        params["dates"] = normalized_dates
    if extra_params:
        params.update({key: value for key, value in extra_params.items() if value})
    if params:
        return f"{base_url}?{urlencode(params)}"
    return base_url


def _build_scoreboard_url(league_key: str, game_date: Optional[date | str]) -> str:
    league_path = get_league_path(league_key)
    if league_path is None:
        raise ValueError(f"Unsupported league key: {league_key}")

    parts = league_path.split("/")
    if len(parts) < 3 or parts[0] != "sports":
        raise ValueError(f"Unsupported league path: {league_path}")

    sport = parts[1]
    league = parts[2]
    return build_scoreboard_url(sport, league, game_date)


def fetch_scoreboard(league_key: str, game_date: Optional[date | str] = None) -> dict:
    """Fetch ESPN scoreboard data for a league and optional date.

    Returns parsed JSON on success. On failure, returns a controlled error dict.
    """

    try:
        url = _build_scoreboard_url(league_key, game_date)
    except ValueError as exc:
        safe_date = None
        try:
            safe_date = normalize_dates(game_date)
        except ValueError:
            safe_date = None
        return {
            "ok": False,
            "error": str(exc),
            "league": league_key,
            "date": safe_date,
        }

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json",
    }

    last_error: str | None = None
    last_status: int | None = None
    last_body_snippet: str | None = None
    for attempt in range(DEFAULT_RETRIES):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", None)
                payload = response.read().decode("utf-8")
                if status and status != 200:
                    body_snippet = payload[:300]
                    logger.error(
                        "ESPN scoreboard non-200 status=%s body=%s",
                        status,
                        body_snippet,
                    )
                    return {
                        "ok": False,
                        "error": "ESPN returned non-200 response",
                        "status": status,
                        "body": body_snippet,
                        "league": league_key,
                        "date": normalize_dates(game_date),
                        "url": url,
                    }
                return json.loads(payload)
        except HTTPError as exc:
            last_status = exc.code
            body = exc.read().decode("utf-8") if exc.fp else ""
            last_body_snippet = body[:300]
            logger.error(
                "ESPN scoreboard HTTPError status=%s body=%s",
                last_status,
                last_body_snippet,
            )
            last_error = str(exc)
            if attempt < DEFAULT_RETRIES - 1:
                time.sleep(DEFAULT_BACKOFF_SECONDS * (2**attempt))
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if attempt < DEFAULT_RETRIES - 1:
                time.sleep(DEFAULT_BACKOFF_SECONDS * (2**attempt))

    return {
        "ok": False,
        "error": "Failed to fetch ESPN scoreboard",
        "details": last_error,
        "status": last_status,
        "body": last_body_snippet,
        "league": league_key,
        "date": normalize_dates(game_date),
        "url": url,
    }
