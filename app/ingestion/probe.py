"""Quick probe for ESPN scoreboard availability."""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime

from app.ingestion.espn_client import fetch_scoreboard
from app.ingestion.leagues import LEAGUE_PATHS


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe ESPN scoreboard for a league/date and print event count.",
    )
    parser.add_argument(
        "--league",
        type=str,
        default="NBA",
        help="League key (e.g., NBA, NHL, NFL).",
    )
    parser.add_argument(
        "--date",
        type=str,
        default="today",
        help="Date in YYYY-MM-DD or YYYYMMDD format (default: today).",
    )
    return parser.parse_args()


def _normalize_league(raw: str) -> str:
    value = raw.strip().upper()
    if value not in LEAGUE_PATHS:
        supported = ", ".join(sorted(LEAGUE_PATHS))
        raise SystemExit(
            f"Unsupported league: {value}. Supported leagues: {supported}"
        )
    return value


def _resolve_date(raw: str) -> date | str:
    cleaned = raw.strip().lower()
    if cleaned == "today":
        return date.today()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return raw


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args()
    league = _normalize_league(args.league)
    target_date = _resolve_date(args.date)

    payload = fetch_scoreboard(league, target_date)
    if payload.get("error"):
        logging.error("ESPN error: %s", payload.get("error"))
        details = payload.get("details")
        if details:
            logging.error("Details: %s", details)
        raise SystemExit(1)

    events = payload.get("events") or []
    logging.info(
        "Fetched %s events for league=%s date=%s",
        len(events),
        league,
        args.date,
    )


if __name__ == "__main__":
    main()
