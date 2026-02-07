from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from .db import Base

class Pick(Base):
    __tablename__ = "picks"

    id = Column(Integer, primary_key=True, index=True)

    # Info del pick
    sport = Column(String, default="")           # NBA, NFL, Soccer...
    event = Column(String, default="")           # "Lakers vs Heat"
    market = Column(String, default="")          # ML, Spread, Total...
    selection = Column(String, default="")       # "Lakers -2.5"
    odds = Column(Float, default=0.0)            # -110 -> -110.0, +120 -> 120.0
    stake = Column(Float, default=1.0)           # unidades (1.0 = 1u)

    # IA / origen
    source = Column(String, default="AI")        # "AI", "Manual", "Friend", etc.
    gpt_name = Column(String, default="")        # nombre de tu GPT (si quieres)
    reasoning = Column(Text, default="")         # explicación / texto del GPT

    # Resultado
    result = Column(String, default="PENDING")   # PENDING | WON | LOST | PUSH
    profit = Column(Float, default=0.0)          # en unidades (se calcula al cerrar)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
