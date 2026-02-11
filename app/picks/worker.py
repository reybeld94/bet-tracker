from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import socket
import traceback

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
        # Count total queued jobs for visibility
        total_queued = db.query(PickJob).filter(PickJob.status == "queued").count()
        eligible = db.query(PickJob).filter(
            PickJob.status == "queued",
            PickJob.run_at_utc <= now,
        ).count()
        logger.debug(
            "Job check: total_queued=%d eligible_now=%d (concurrency=%d)",
            total_queued, eligible, concurrency,
        )

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
        if job_ids:
            logger.info("Claimed %d job(s): %s", len(job_ids), job_ids)
    return job_ids


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "none"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _queue_snapshot() -> dict[str, str | int]:
    now = _utcnow()
    with SessionLocal() as db:
        total = db.query(PickJob).count()
        queued = db.query(PickJob).filter(PickJob.status == "queued").count()
        eligible = db.query(PickJob).filter(
            PickJob.status == "queued",
            PickJob.run_at_utc <= now,
        ).count()
        running = db.query(PickJob).filter(PickJob.status == "running").count()
        failed = db.query(PickJob).filter(PickJob.status == "failed").count()
        done = db.query(PickJob).filter(PickJob.status == "done").count()
        next_job = (
            db.query(PickJob)
            .filter(PickJob.status == "queued")
            .order_by(PickJob.run_at_utc.asc())
            .first()
        )

    return {
        "total": total,
        "queued": queued,
        "eligible": eligible,
        "running": running,
        "done": done,
        "failed": failed,
        "next_queued_run_at": _format_dt(next_job.run_at_utc if next_job else None),
        "now_utc": _format_dt(now),
    }


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
    logger.info("Processing job #%d ...", job_id)
    with SessionLocal() as db:
        job = db.query(PickJob).filter(PickJob.id == job_id).one_or_none()
        if not job or job.status != "running" or job.lock_owner != lock_owner:
            logger.warning("Job #%d: skipped (status=%s, owner=%s)",
                           job_id, job.status if job else "N/A", job.lock_owner if job else "N/A")
            return

        try:
            game = db.query(Game).filter(Game.id == job.game_id).one_or_none()
            if not game:
                raise RuntimeError("Game not found for job.")
            logger.info("Job #%d: game=%s vs %s (%s) start=%s",
                        job_id, game.home_team, game.away_team, game.league,
                        game.start_time_utc)

            existing_pick = db.query(Pick).filter(Pick.game_id == job.game_id).one_or_none()
            if existing_pick is not None:
                logger.info("Job #%d: pick already exists for game #%d, marking done", job_id, job.game_id)
                job.status = "done"
                job.updated_at_utc = _utcnow()
                db.commit()
                return

            logger.info("Job #%d: calling OpenAI (model=%s, effort=%s) ...",
                        job_id, settings_snapshot.openai_model, settings_snapshot.openai_reasoning_effort)
            payload = build_game_payload(game, settings_snapshot)
            ai_payload, raw_ai_json = request_pick(payload, settings_snapshot)

            if payload["odds"] is None:
                logger.info("Job #%d: no odds available, coercing to NO_BET", job_id)
                ai_payload = _coerce_no_odds(ai_payload)

            _upsert_pick(db, game.id, ai_payload, raw_ai_json)
            logger.info("Job #%d: pick saved -> result=%s market=%s confidence=%s ev=%s",
                        job_id, ai_payload.get("result"), ai_payload.get("market"),
                        ai_payload.get("confidence"), ai_payload.get("ev"))

            job.status = "done"
            job.updated_at_utc = _utcnow()
            db.commit()
        except Exception as exc:
            exc_name = type(exc).__name__
            exc_message = str(exc).strip() or "(no message)"
            error_summary = f"{exc_name}: {exc_message}"
            logger.error("Job #%d FAILED: %s", job_id, error_summary, exc_info=True)
            db.rollback()
            job = db.query(PickJob).filter(PickJob.id == job_id).one_or_none()
            if not job:
                return
            job.attempts += 1
            job.last_error = error_summary
            job.updated_at_utc = _utcnow()
            if job.attempts <= settings_snapshot.auto_picks_max_retries:
                job.status = "queued"
                job.run_at_utc = _utcnow()
                logger.warning(
                    "Job #%d re-queued (%d/%d attempts) due to %s",
                    job_id,
                    job.attempts,
                    settings_snapshot.auto_picks_max_retries,
                    error_summary,
                )
            else:
                job.status = "failed"
                trace_tail = traceback.format_exc(limit=6).strip().replace("\n", " | ")
                logger.error(
                    "Job #%d exhausted retries (%d/%d) | last_error=%s | trace=%s",
                    job_id,
                    job.attempts,
                    settings_snapshot.auto_picks_max_retries,
                    error_summary,
                    trace_tail,
                )
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
    logger.info("Worker started (lock_owner=%s)", lock_owner)
    idle_polls = 0

    while not stop_event.is_set():
        with SessionLocal() as db:
            settings = get_or_create_settings(db)
            settings_snapshot = snapshot_settings(settings)
            has_key = bool(settings_snapshot.openai_api_key_enc)
            picks_enabled = bool(settings_snapshot.auto_picks_enabled)

        if not picks_enabled:
            logger.warning("Worker poll: auto_picks_enabled=false — worker idle")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings_snapshot.auto_picks_poll_seconds,
                )
            except asyncio.TimeoutError:
                continue
            continue

        if not has_key:
            logger.warning("Worker poll: no OpenAI API key configured — skipping")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings_snapshot.auto_picks_poll_seconds,
                )
            except asyncio.TimeoutError:
                continue
            continue
        else:
            logger.debug(
                "Worker poll: api_key=configured model=%s concurrency=%d poll=%ds",
                settings_snapshot.openai_model,
                settings_snapshot.auto_picks_concurrency,
                settings_snapshot.auto_picks_poll_seconds,
            )

        job_ids = _claim_jobs(settings_snapshot.auto_picks_concurrency, lock_owner)
        if not job_ids:
            idle_polls += 1
            if idle_polls == 1 or idle_polls % 10 == 0:
                snapshot = _queue_snapshot()
                logger.info(
                    "Worker idle: no eligible jobs | total=%s queued=%s eligible=%s running=%s done=%s failed=%s "
                    "next_queued_run_at=%s now_utc=%s",
                    snapshot["total"],
                    snapshot["queued"],
                    snapshot["eligible"],
                    snapshot["running"],
                    snapshot["done"],
                    snapshot["failed"],
                    snapshot["next_queued_run_at"],
                    snapshot["now_utc"],
                )
            else:
                logger.debug("No eligible jobs, sleeping %ds ...", settings_snapshot.auto_picks_poll_seconds)
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=settings_snapshot.auto_picks_poll_seconds,
                )
            except asyncio.TimeoutError:
                continue
            continue

        idle_polls = 0

        semaphore = asyncio.Semaphore(settings_snapshot.auto_picks_concurrency)
        tasks = [
            asyncio.create_task(_process_job(job_id, settings_snapshot, lock_owner, semaphore))
            for job_id in job_ids
        ]
        await asyncio.gather(*tasks)
    logger.info("Worker stopped.")


def main() -> None:
    try:
        asyncio.run(run_worker())
    except OpenAIClientError:
        logger.exception("OpenAI client error encountered in worker.")
    except KeyboardInterrupt:
        logger.info("Worker interrupted.")


if __name__ == "__main__":
    main()
