"""Sync games from ESPN into the local database."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from sqlalchemy.orm import Session

from app.db import Base, SessionLocal, engine
from app.ingestion.espn_client import fetch_scoreboard
from app.ingestion.espn_parser import parse_scoreboard
from app.ingestion.schema import GameIngestDTO
from app.models import Game

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    total_fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


def _serialize_raw(raw: dict | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))


def _update_game_from_dto(game: Game, dto: GameIngestDTO) -> bool:
    changed = False

    if game.status != dto.status:
        game.status = dto.status
        changed = True
    if game.home_score != dto.home_score:
        game.home_score = dto.home_score
        changed = True
    if game.away_score != dto.away_score:
        game.away_score = dto.away_score
        changed = True
    if game.start_time_utc != dto.start_time_utc:
        game.start_time_utc = dto.start_time_utc
        changed = True

    if changed:
        game.raw_json = _serialize_raw(dto.raw)

    return changed


def _insert_game(db: Session, dto: GameIngestDTO) -> None:
    game = Game(
        provider=dto.provider,
        provider_event_id=dto.provider_event_id,
        sport=dto.sport,
        league=dto.league,
        start_time_utc=dto.start_time_utc,
        status=dto.status,
        home_team=dto.home_team_name,
        away_team=dto.away_team_name,
        home_score=dto.home_score,
        away_score=dto.away_score,
        raw_json=_serialize_raw(dto.raw),
    )
    db.add(game)


def _upsert_games(db: Session, games: Iterable[GameIngestDTO], result: SyncResult) -> None:
    for game_dto in games:
        try:
            existing = (
                db.query(Game)
                .filter(
                    Game.provider == game_dto.provider,
                    Game.provider_event_id == game_dto.provider_event_id,
                )
                .one_or_none()
            )

            if existing:
                if _update_game_from_dto(existing, game_dto):
                    result.updated += 1
                    logger.info(
                        "Updated game provider_event_id=%s",
                        game_dto.provider_event_id,
                    )
                else:
                    result.skipped += 1
                    logger.info(
                        "Skipped unchanged game provider_event_id=%s",
                        game_dto.provider_event_id,
                    )
            else:
                _insert_game(db, game_dto)
                result.inserted += 1
                logger.info(
                    "Inserted game provider_event_id=%s",
                    game_dto.provider_event_id,
                )
        except Exception:
            db.rollback()
            result.errors += 1
            logger.exception(
                "Failed upserting game provider_event_id=%s",
                game_dto.provider_event_id,
            )


def sync_games_for_date(game_date: date, leagues: list[str]) -> SyncResult:
    """Fetch, parse, and upsert games for the requested date + leagues."""

    Base.metadata.create_all(bind=engine)
    result = SyncResult()

    with SessionLocal() as db:
        for league_key in leagues:
            logger.info("Fetching scoreboard for league=%s date=%s", league_key, game_date)
            payload = fetch_scoreboard(league_key, game_date)
            if payload.get("error"):
                result.errors += 1
                logger.error(
                    "Fetch error league=%s date=%s error=%s details=%s",
                    league_key,
                    game_date,
                    payload.get("error"),
                    payload.get("details"),
                )
                continue

            parsed_games = parse_scoreboard(payload, league_key)
            result.total_fetched += len(parsed_games)
            logger.info(
                "Parsed %s games for league=%s date=%s",
                len(parsed_games),
                league_key,
                game_date,
            )

            _upsert_games(db, parsed_games, result)

        db.commit()

    return result
