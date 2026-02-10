from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import logging

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion.leagues import LEAGUE_PATHS
from app.models import Game, Pick, PickJob

logger = logging.getLogger(__name__)


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


def _enqueue_for_game(db: Session, game: Game) -> bool:
    if not game.start_time_utc:
        return False
    if game.status.lower() not in {"scheduled", "in_progress"}:
        return False
    existing_pick = db.query(Pick).filter(Pick.game_id == game.id).one_or_none()
    if existing_pick is not None:
        return False
    existing = db.query(PickJob).filter(PickJob.game_id == game.id).one_or_none()
    if existing:
        # Re-queue failed jobs so they get another chance
        if existing.status == "failed":
            existing.status = "queued"
            existing.locked_at_utc = None
            existing.lock_owner = None
            existing.updated_at_utc = datetime.now(timezone.utc)
            logger.info("Re-queued failed job #%d for game #%d", existing.id, game.id)
            return True
        return False
    run_at = game.start_time_utc - timedelta(hours=2)
    now = datetime.now(timezone.utc)
    job = PickJob(
        game_id=game.id,
        run_at_utc=run_at,
        status="queued",
        attempts=0,
        locked_at_utc=None,
        lock_owner=None,
        last_error=None,
        created_at_utc=now,
        updated_at_utc=now,
    )
    db.add(job)
    return True


def enqueue_for_date(target_date: date, leagues: list[str]) -> int:
    start_utc, end_utc = _utc_day_range(target_date)
    created = 0
    with SessionLocal() as db:
        query = db.query(Game).filter(
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
    """Enqueue unanalyzed games starting within horizon hours (or sooner)."""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=horizon_hours)
    created = 0
    with SessionLocal() as db:
        query = db.query(Game).filter(
            Game.start_time_utc.isnot(None),
            Game.start_time_utc <= horizon,
            Game.status.in_(["scheduled", "in_progress"]),
        )
        if leagues:
            query = query.filter(Game.league.in_(leagues))
        games = query.order_by(Game.start_time_utc.asc()).all()
        for game in games:
            if _enqueue_for_game(db, game):
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
