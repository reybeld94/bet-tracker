from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class PickOut(BaseModel):
    id: int
    game_id: int
    result: str
    market: Optional[str]
    emoji: str
    selection: Optional[str]
    line: Optional[float]
    odds_format: Optional[str]
    odds: Optional[float]
    p_est: float
    p_implied: Optional[float]
    ev: Optional[float]
    confidence: int
    stake_u: float
    high_prob_low_payout: bool
    is_value: bool
    reasons_json: str
    risks_json: str
    triggers_json: str
    missing_data_json: str
    as_of_utc: str
    notes: str
    raw_ai_json: str
    created_at_utc: Optional[datetime]
    updated_at_utc: Optional[datetime]

    class Config:
        from_attributes = True


class PickJobOut(BaseModel):
    id: int
    game_id: int
    run_at_utc: datetime
    status: str
    attempts: int
    locked_at_utc: Optional[datetime]
    lock_owner: Optional[str]
    last_error: Optional[str]
    created_at_utc: Optional[datetime]
    updated_at_utc: Optional[datetime]

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
