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
