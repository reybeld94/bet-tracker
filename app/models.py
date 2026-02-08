from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .db import Base

class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_events_provider_event_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=True, default=None)
    provider_event_id = Column(String, nullable=True, default=None)
    sport = Column(String, nullable=False, default="")
    league = Column(String, nullable=False, default="")
    home_team = Column(String, nullable=False, default="")
    away_team = Column(String, nullable=False, default="")
    start_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default="SCHEDULED")
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    picks = relationship("Pick", back_populates="event")


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_games_provider_event_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False, default="")
    provider_event_id = Column(String, nullable=False, default="")
    sport = Column(String, nullable=False, default="")
    league = Column(String, nullable=False, default="")
    start_time_utc = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default="SCHEDULED")
    home_team = Column(String, nullable=False, default="")
    away_team = Column(String, nullable=False, default="")
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    raw_json = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

class Pick(Base):
    __tablename__ = "picks"

    id = Column(Integer, primary_key=True, index=True)

    # Info del pick
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    sportsbook = Column(String, default="")
    market_type = Column(String, default="")
    period = Column(String, default="FG")
    line = Column(Float, nullable=True)
    side = Column(String, default="")
    odds = Column(Float, default=0.0)            # -110 -> -110.0, +120 -> 120.0
    stake = Column(Float, default=0.0)           # unidades (1.0 = 1u)
    recommendation = Column(String, default="")
    status = Column(String, default="DRAFT")

    # IA / origen
    source = Column(String, default="AI")        # "AI", "Manual", "Friend", etc.
    gpt_name = Column(String, default="")        # nombre de tu GPT (si quieres)
    reasoning = Column(Text, default="")         # explicación / texto del GPT

    # Resultado
    result = Column(String, default="PENDING")   # PENDING | WON | LOST | PUSH
    profit = Column(Float, default=0.0)          # en unidades (se calcula al cerrar)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    event = relationship("Event", back_populates="picks")
