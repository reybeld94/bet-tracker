from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.sql import func
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

class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True)
    openai_api_key_enc = Column(Text, nullable=True)
    openai_model = Column(String, nullable=False, default="gpt-5")
    openai_reasoning_effort = Column(String, nullable=False, default="high")
    auto_picks_enabled = Column(Boolean, nullable=False, default=True)
    auto_picks_concurrency = Column(Integer, nullable=False, default=2)
    auto_picks_poll_seconds = Column(Integer, nullable=False, default=30)
    auto_picks_max_retries = Column(Integer, nullable=False, default=2)
    allow_totals_default = Column(Boolean, nullable=False, default=False)
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PickJob(Base):
    __tablename__ = "pick_jobs"
    __table_args__ = (
        UniqueConstraint("game_id", name="uq_pick_jobs_game_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    run_at_utc = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    locked_at_utc = Column(DateTime(timezone=True), nullable=True)
    lock_owner = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now())
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Pick(Base):
    __tablename__ = "picks"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    result = Column(String, nullable=False, default="NO_BET")
    market = Column(String, nullable=True)
    emoji = Column(String, nullable=False, default="")
    selection = Column(String, nullable=True)
    line = Column(Float, nullable=True)
    odds_format = Column(String, nullable=True)
    odds = Column(Float, nullable=True)
    p_est = Column(Float, nullable=False, default=0.0)
    p_implied = Column(Float, nullable=True)
    ev = Column(Float, nullable=True)
    confidence = Column(Integer, nullable=False, default=0)
    stake_u = Column(Float, nullable=False, default=0.0)
    high_prob_low_payout = Column(Boolean, nullable=False, default=False)
    is_value = Column(Boolean, nullable=False, default=False)
    reasons_json = Column(Text, nullable=False, default="[]")
    risks_json = Column(Text, nullable=False, default="[]")
    triggers_json = Column(Text, nullable=False, default="[]")
    missing_data_json = Column(Text, nullable=False, default="[]")
    as_of_utc = Column(String, nullable=False, default="")
    notes = Column(Text, nullable=False, default="")
    raw_ai_json = Column(Text, nullable=False, default="")
    created_at_utc = Column(DateTime(timezone=True), server_default=func.now())
    updated_at_utc = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
