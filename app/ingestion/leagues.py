"""Supported leagues mapping for ESPN endpoints."""

LEAGUE_PATHS: dict[str, str] = {
    "NBA": "sports/basketball/nba",
    "NHL": "sports/hockey/nhl",
    "NFL": "sports/football/nfl",
}


def get_league_path(league_key: str) -> str | None:
    """Return ESPN path segment for a league key (e.g., NBA).

    Returns None when the league is not supported.
    """

    return LEAGUE_PATHS.get(league_key.upper())
