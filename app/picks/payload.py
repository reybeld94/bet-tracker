from __future__ import annotations

from datetime import datetime, timezone


def build_game_payload(game, settings) -> dict:
    return {
        "sport": game.sport,
        "league": game.league,
        "home_team": game.home_team,
        "away_team": game.away_team,
        "start_time_utc": game.start_time_utc.isoformat() if game.start_time_utc else None,
        "odds": None,
        "allow_totals": settings.allow_totals_default,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "sources": [],
    }
