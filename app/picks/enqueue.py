from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import logging

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion.leagues import LEAGUE_PATHS
from app.models import Game, Pick, PickJob

logger = logging.getLogger(__name__)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_leagues(raw: str) -> list[str]:
    leagues = [league.strip().upper() for league in raw.split(",") if league.strip()]
    invalid = [league for league in leagues if league not in LEAGUE_PATHS]
    if invalid:
        raise ValueError(f"Unsupported leagues: {', '.join(invalid)}")
    return leagues


def _utc_day_range(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _enqueue_for_game(
    db: Session,
    game: Game,
    *,
    now: datetime | None = None,
    pregame_window_hours: int = 2,
) -> bool:
    if not game.start_time_utc:
        return False
    if game.status.lower() != "scheduled":
        return False

    now_utc = now or datetime.now(timezone.utc)
    game_start_utc = _ensure_utc(game.start_time_utc)
    window_start = game_start_utc - timedelta(hours=pregame_window_hours)
    if not (window_start <= now_utc <= game_start_utc):
        return False

    existing_pick = db.query(Pick).filter(Pick.game_id == game.id).one_or_none()
    if existing_pick is not None:
        return False

    run_at = now_utc

    existing = db.query(PickJob).filter(PickJob.game_id == game.id).one_or_none()
    if existing:
        if existing.status != "failed":
            return False
        existing.status = "queued"
        existing.attempts = 0
        existing.run_at_utc = now_utc
        existing.locked_at_utc = None
        existing.lock_owner = None
        existing.last_error = None
        existing.updated_at_utc = now_utc
        return True

    job = PickJob(
        game_id=game.id,
        run_at_utc=run_at,
        status="queued",
        attempts=0,
        locked_at_utc=None,
        lock_owner=None,
        last_error=None,
        created_at_utc=now_utc,
        updated_at_utc=now_utc,
    )
    db.add(job)
    return True


def enqueue_for_date(target_date: date, leagues: list[str]) -> int:
    start_utc, end_utc = _utc_day_range(target_date)
    created = 0
    with SessionLocal() as db:
        query = db.query(Game).filter(
            Game.provider == "espn",
            Game.start_time_utc.isnot(None),
            Game.start_time_utc >= start_utc,
            Game.start_time_utc < end_utc,
        )
        if leagues:
            query = query.filter(Game.league.in_(leagues))
        games = query.order_by(Game.start_time_utc.asc()).all()
        for game in games:
            if _enqueue_for_game(db, game):
                created += 1
        db.commit()
    return created


def enqueue_due_games(leagues: list[str], horizon_hours: int = 2) -> int:
    """Enqueue unanalyzed games when current time is in pregame window.

    A game is eligible when now is between (start - horizon_hours) and start.
    """
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=horizon_hours)
    created = 0
    with SessionLocal() as db:
        query = db.query(Game).filter(
            Game.provider == "espn",
            Game.start_time_utc.isnot(None),
            Game.start_time_utc >= now,
            Game.start_time_utc <= horizon,
            Game.status == "scheduled",
        )
        if leagues:
            query = query.filter(Game.league.in_(leagues))
        games = query.order_by(Game.start_time_utc.asc()).all()
        for game in games:
            if _enqueue_for_game(db, game, now=now, pregame_window_hours=horizon_hours):
                created += 1
        db.commit()
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Enqueue auto-picks jobs.")
    parser.add_argument("--today", action="store_true", help="Use today's date")
    parser.add_argument("--date", help="Date YYYY-MM-DD")
    parser.add_argument("--leagues", default="NBA,NHL")
    args = parser.parse_args()

    if not args.today and not args.date:
        raise SystemExit("Provide --today or --date")
    target_date = date.today() if args.today else date.fromisoformat(args.date)
    leagues = _parse_leagues(args.leagues) if args.leagues else []

    created = enqueue_for_date(target_date, leagues)
    logger.info("Enqueued %s pick jobs for %s", created, target_date.isoformat())


if __name__ == "__main__":
    main()
