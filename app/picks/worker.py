from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import socket

from app.ai.openai_client import OpenAIClientError, request_pick
from app.db import SessionLocal
from app.models import Game, Pick, PickJob
from app.picks.payload import build_game_payload
from app.settings import get_or_create_settings, snapshot_settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _claim_jobs(concurrency: int, lock_owner: str) -> list[int]:
    now = _utcnow()
    with SessionLocal() as db:
        jobs = (
            db.query(PickJob)
            .filter(
                PickJob.status == "queued",
                PickJob.run_at_utc <= now,
            )
            .order_by(PickJob.run_at_utc.asc())
            .limit(concurrency)
            .all()
        )
        job_ids: list[int] = []
        for job in jobs:
            job.status = "running"
            job.locked_at_utc = now
            job.lock_owner = lock_owner
            job.updated_at_utc = now
            job_ids.append(job.id)
        db.commit()
    return job_ids


def _coerce_no_odds(ai_payload: dict, missing_label: str = "odds") -> dict:
    missing_data = list(ai_payload.get("missing_data") or [])
    if missing_label not in missing_data:
        missing_data.append(missing_label)
    ai_payload["missing_data"] = missing_data
    ai_payload["result"] = "NO_BET"
    ai_payload["stake_u"] = 0
    ai_payload["is_value"] = False
    return ai_payload


def _upsert_pick(db, game_id: int, ai_payload: dict, raw_ai_json: str) -> None:
    now = _utcnow()
    pick = db.query(Pick).filter(Pick.game_id == game_id).one_or_none()
    if not pick:
        pick = Pick(game_id=game_id, created_at_utc=now)
        db.add(pick)

    pick.result = ai_payload["result"]
    pick.market = ai_payload["market"]
    pick.emoji = ai_payload["emoji"]
    pick.selection = ai_payload["selection"]
    pick.line = ai_payload["line"]
    pick.odds_format = ai_payload["odds_format"]
    pick.odds = ai_payload["odds"]
    pick.p_est = ai_payload["p_est"]
    pick.p_implied = ai_payload["p_implied"]
    pick.ev = ai_payload["ev"]
    pick.confidence = ai_payload["confidence"]
    pick.stake_u = ai_payload["stake_u"]
    pick.high_prob_low_payout = ai_payload["high_prob_low_payout"]
    pick.is_value = ai_payload["is_value"]
    pick.reasons_json = json.dumps(ai_payload["reasons"], ensure_ascii=False)
    pick.risks_json = json.dumps(ai_payload["risks"], ensure_ascii=False)
    pick.triggers_json = json.dumps(ai_payload["triggers"], ensure_ascii=False)
    pick.missing_data_json = json.dumps(ai_payload["missing_data"], ensure_ascii=False)
    pick.as_of_utc = ai_payload["as_of_utc"]
    pick.notes = ai_payload["notes"]
    pick.raw_ai_json = raw_ai_json
    pick.updated_at_utc = now


def _process_job_sync(job_id: int, settings_snapshot, lock_owner: str) -> None:
    with SessionLocal() as db:
        job = db.query(PickJob).filter(PickJob.id == job_id).one_or_none()
        if not job or job.status != "running" or job.lock_owner != lock_owner:
            return

        try:
            game = db.query(Game).filter(Game.id == job.game_id).one_or_none()
            if not game:
                raise RuntimeError("Game not found for job.")

            existing_pick = db.query(Pick).filter(Pick.game_id == job.game_id).one_or_none()
            if existing_pick is not None:
                job.status = "done"
                job.updated_at_utc = _utcnow()
                db.commit()
                return

            payload = build_game_payload(game, settings_snapshot)
            ai_payload, raw_ai_json = request_pick(payload, settings_snapshot)

            if payload["odds"] is None:
                ai_payload = _coerce_no_odds(ai_payload)

            _upsert_pick(db, game.id, ai_payload, raw_ai_json)

            job.status = "done"
            job.updated_at_utc = _utcnow()
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.query(PickJob).filter(PickJob.id == job_id).one_or_none()
            if not job:
                return
            job.attempts += 1
            job.last_error = str(exc)
            job.updated_at_utc = _utcnow()
            job.status = "failed"
            job.locked_at_utc = None
            job.lock_owner = None
            db.commit()


async def _process_job(job_id: int, settings_snapshot, lock_owner: str, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        await asyncio.to_thread(_process_job_sync, job_id, settings_snapshot, lock_owner)


async def run_worker() -> None:
    hostname = socket.gethostname()
    pid = os.getpid()
    lock_owner = f"{hostname}:{pid}"

    while True:
        with SessionLocal() as db:
            settings = get_or_create_settings(db)
            settings_snapshot = snapshot_settings(settings)

        job_ids = _claim_jobs(settings_snapshot.auto_picks_concurrency, lock_owner)
        if not job_ids:
            await asyncio.sleep(settings_snapshot.auto_picks_poll_seconds)
            continue

        semaphore = asyncio.Semaphore(settings_snapshot.auto_picks_concurrency)
        tasks = [
            asyncio.create_task(_process_job(job_id, settings_snapshot, lock_owner, semaphore))
            for job_id in job_ids
        ]
        await asyncio.gather(*tasks)


async def run_worker_with_shutdown(stop_event: asyncio.Event) -> None:
    """Run worker loop until stop_event is set."""
    hostname = socket.gethostname()
    pid = os.getpid()
    lock_owner = f"{hostname}:{pid}"

    while not stop_event.is_set():
        with SessionLocal() as db:
            settings = get_or_create_settings(db)
            settings_snapshot = snapshot_settings(settings)

        job_ids = _claim_jobs(settings_snapshot.auto_picks_concurrency, lock_owner)
        if not job_ids:
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings_snapshot.auto_picks_poll_seconds,
                )
            except asyncio.TimeoutError:
                continue
            continue

        semaphore = asyncio.Semaphore(settings_snapshot.auto_picks_concurrency)
        tasks = [
            asyncio.create_task(_process_job(job_id, settings_snapshot, lock_owner, semaphore))
            for job_id in job_ids
        ]
        await asyncio.gather(*tasks)


def main() -> None:
    try:
        asyncio.run(run_worker())
    except OpenAIClientError:
        logger.exception("OpenAI client error encountered in worker.")
    except KeyboardInterrupt:
        logger.info("Worker interrupted.")


if __name__ == "__main__":
    main()
