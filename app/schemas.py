from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class PickCreate(BaseModel):
    event_id: Optional[int] = None
    sportsbook: str = ""
    market_type: str = ""
    period: str = "FG"
    line: Optional[float] = None
    side: str = ""
    odds: float = 0.0
    stake: float = 0.0
    recommendation: str = ""
    status: str = "DRAFT"
    source: str = "AI"
    gpt_name: str = ""
    reasoning: str = ""

class PickOut(BaseModel):
    id: int
    event_id: Optional[int]
    sportsbook: str
    market_type: str
    period: str
    line: Optional[float]
    side: str
    odds: float
    stake: float
    recommendation: str
    status: str
    source: str
    gpt_name: str
    reasoning: str
    result: str
    profit: float

    class Config:
        from_attributes = True


class GameOut(BaseModel):
    id: int
    provider: str
    provider_event_id: str
    sport: str
    league: str
    start_time_utc: Optional[datetime]
    status: str
    home_team: str
    away_team: str
    home_score: Optional[int]
    away_score: Optional[int]

    class Config:
        from_attributes = True


class GamesTodayResponse(BaseModel):
    games: list[GameOut]
    date: str
    league: Optional[str] = None
    count: int
    message: Optional[str] = None
