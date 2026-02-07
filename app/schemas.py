from pydantic import BaseModel
from typing import Optional

class PickCreate(BaseModel):
    sport: str = ""
    event: str = ""
    market: str = ""
    selection: str = ""
    odds: float = 0.0
    stake: float = 1.0
    source: str = "AI"
    gpt_name: str = ""
    reasoning: str = ""

class PickOut(BaseModel):
    id: int
    sport: str
    event: str
    market: str
    selection: str
    odds: float
    stake: float
    source: str
    gpt_name: str
    reasoning: str
    result: str
    profit: float

    class Config:
        from_attributes = True
