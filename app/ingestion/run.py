"""CLI entrypoint for scheduled ingestion runs."""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime

from app.ingestion.leagues import LEAGUE_PATHS
from app.ingestion.sync import sync_games_for_date


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ESPN ingestion for a given date and league list.",
    )

    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument(
        "--today",
        action="store_true",
        help="Use today's date for ingestion.",
    )
    date_group.add_argument(
        "--date",
        type=str,
        help="Date to ingest in YYYY-MM-DD format.",
    )

    parser.add_argument(
        "--leagues",
        type=str,
        required=True,
        help="Comma-separated list of leagues (e.g., NBA,NHL).",
    )

    return parser.parse_args()


def _parse_leagues(raw: str) -> list[str]:
    leagues = [league.strip().upper() for league in raw.split(",") if league.strip()]
    invalid = [league for league in leagues if league not in LEAGUE_PATHS]
    if invalid:
        supported = ", ".join(sorted(LEAGUE_PATHS))
        raise SystemExit(
            f"Unsupported leagues: {', '.join(invalid)}. Supported: {supported}"
        )
    if not leagues:
        raise SystemExit("No leagues provided. Use --leagues NBA,NHL,...")
    return leagues


def _resolve_date(args: argparse.Namespace) -> date:
    if args.date:
        return datetime.strptime(args.date, "%Y-%m-%d").date()
    return date.today()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    args = _parse_args()
    leagues = _parse_leagues(args.leagues)
    target_date = _resolve_date(args)

    logging.info("Starting ingestion date=%s leagues=%s", target_date, ",".join(leagues))
    result = sync_games_for_date(target_date, leagues)
    logging.info(
        "Done: fetched=%s inserted=%s updated=%s skipped=%s errors=%s",
        result.total_fetched,
        result.inserted,
        result.updated,
        result.skipped,
        result.errors,
    )


if __name__ == "__main__":
    main()
