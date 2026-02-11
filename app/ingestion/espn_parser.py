"""Parser for ESPN scoreboard payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from app.ingestion.schema import GameIngestDTO


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_start_time(event: dict[str, Any]) -> datetime | None:
    date_value = event.get("date")
    if isinstance(date_value, str):
        try:
            return datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def _normalize_status(status: dict[str, Any]) -> str:
    status_type = status.get("type", {}) if isinstance(status, dict) else {}
    state = status_type.get("state") or status_type.get("name")
    if isinstance(state, str):
        state_lower = state.lower()
        if "postpon" in state_lower:
            return "postponed"
        if "cancel" in state_lower:
            return "canceled"
        if state_lower in {"pre", "scheduled"}:
            return "scheduled"
        if state_lower in {"in", "in_progress", "in progress"}:
            return "in_progress"
        if state_lower in {"post", "final", "finals"}:
            return "final"
    description = status_type.get("description") or ""
    if isinstance(description, str):
        description_lower = description.lower()
        if "postpon" in description_lower:
            return "postponed"
        if "cancel" in description_lower:
            return "canceled"
        if "final" in description_lower:
            return "final"
        if "in progress" in description_lower:
            return "in_progress"
    return "scheduled"


def _extract_sport(scoreboard_json: dict[str, Any], league_key: str) -> str:
    sports = scoreboard_json.get("sports")
    if isinstance(sports, list) and sports:
        first_sport = sports[0]
        if isinstance(first_sport, dict):
            name = first_sport.get("name")
            if isinstance(name, str):
                return name.lower()
    league = scoreboard_json.get("league")
    if isinstance(league, dict):
        name = league.get("name")
        if isinstance(name, str):
            return name.lower()
    return league_key.lower()


def _extract_event_ids(event: dict[str, Any]) -> Iterable[str]:
    event_id = event.get("id")
    if isinstance(event_id, str) and event_id:
        yield event_id
    competitions = event.get("competitions")
    if isinstance(competitions, list):
        for competition in competitions:
            if isinstance(competition, dict):
                competition_id = competition.get("id")
                if isinstance(competition_id, str) and competition_id:
                    yield competition_id


def parse_scoreboard(scoreboard_json: dict, league_key: str) -> list[GameIngestDTO]:
    """Parse ESPN scoreboard JSON into GameIngestDTO list."""

    events = scoreboard_json.get("events")
    if not isinstance(events, list):
        return []

    sport = _extract_sport(scoreboard_json, league_key)
    league = league_key.upper()
    seen_event_ids: set[str] = set()
    parsed_games: list[GameIngestDTO] = []

    for event in events:
        if not isinstance(event, dict):
            continue

        competitions = event.get("competitions")
        if not isinstance(competitions, list) or not competitions:
            competitions = [event]

        for competition in competitions:
            if not isinstance(competition, dict):
                continue

            provider_event_id = None
            for candidate_id in _extract_event_ids(competition):
                provider_event_id = candidate_id
                break
            if provider_event_id is None:
                for candidate_id in _extract_event_ids(event):
                    provider_event_id = candidate_id
                    break
            if provider_event_id is None:
                continue
            if provider_event_id in seen_event_ids:
                continue

            seen_event_ids.add(provider_event_id)

            competitors = competition.get("competitors")
            if not isinstance(competitors, list):
                competitors = []

            home = None
            away = None
            for competitor in competitors:
                if not isinstance(competitor, dict):
                    continue
                home_away = competitor.get("homeAway")
                if home_away == "home":
                    home = competitor
                elif home_away == "away":
                    away = competitor

            home_team = home.get("team") if isinstance(home, dict) else {}
            away_team = away.get("team") if isinstance(away, dict) else {}

            home_name = home_team.get("displayName") or home_team.get("name") or "TBD"
            away_name = away_team.get("displayName") or away_team.get("name") or "TBD"

            start_time_utc = _parse_start_time(event)
            if start_time_utc is None:
                continue
            status = _normalize_status(competition.get("status", {}))

            raw_payload = {
                "event_id": event.get("id"),
                "competition_id": competition.get("id"),
                "status": competition.get("status"),
            }

            parsed_games.append(
                GameIngestDTO(
                    provider_event_id=provider_event_id,
                    sport=sport,
                    league=league,
                    start_time_utc=start_time_utc,
                    status=status,
                    home_team_name=str(home_name),
                    away_team_name=str(away_name),
                    home_team_abbrev=(
                        home_team.get("abbreviation") if isinstance(home_team, dict) else None
                    ),
                    away_team_abbrev=(
                        away_team.get("abbreviation") if isinstance(away_team, dict) else None
                    ),
                    home_score=_safe_int(home.get("score") if isinstance(home, dict) else None),
                    away_score=_safe_int(away.get("score") if isinstance(away, dict) else None),
                    raw=raw_payload,
                )
            )

    return parsed_games
