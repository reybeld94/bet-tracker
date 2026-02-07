"""Internal data contract for game ingestion."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


class GameIngestDTO(BaseModel):
    """
    Internal representation of a game used across fetch -> parse -> DB -> API.
    """

    # Required fields
    provider: Literal["espn"] = "espn"
    provider_event_id: str
    sport: str
    league: str
    start_time_utc: datetime
    status: Literal["scheduled", "in_progress", "final", "postponed", "canceled"]
    home_team_name: str
    away_team_name: str

    # Optional fields
    home_team_abbrev: Optional[str] = None
    away_team_abbrev: Optional[str] = None
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    raw: Optional[dict[str, Any] | str] = None
