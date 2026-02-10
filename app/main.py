from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import asyncio
import logging
import os
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingestion.espn_client import fetch_scoreboard, normalize_dates
from app.ingestion.leagues import LEAGUE_PATHS
from app.ingestion.espn_parser import parse_scoreboard
from app.ingestion.sync import sync_games_for_date
from app.log_buffer import install_buffer_handler, get_buffer_handler
from app.models import Game, Pick, PickJob
from app.picks.enqueue import enqueue_due_games
from app.picks.worker import run_worker_with_shutdown
from app.schemas import GameOut, GamesTodayResponse, PickJobOut, PickOut
from app.settings import encrypt_api_key, get_or_create_settings
from app.team_logos import team_logo_url, league_logo_url

app = FastAPI(title="Bet Tracker (Local)")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["team_logo_url"] = team_logo_url
templates.env.globals["league_logo_url"] = league_logo_url
logger = logging.getLogger(__name__)
_auto_ingest_task: asyncio.Task | None = None
_auto_ingest_stop: asyncio.Event | None = None
_auto_worker_task: asyncio.Task | None = None
_auto_worker_stop: asyncio.Event | None = None


def _parse_auto_ingest_leagues(raw: str) -> list[str]:
    leagues = [league.strip().upper() for league in raw.split(",") if league.strip()]
    invalid = [league for league in leagues if league not in LEAGUE_PATHS]
    if invalid:
        logger.error(
            "Auto-ingest disabled due to unsupported leagues: %s. Supported: %s",
            ", ".join(invalid),
            ", ".join(sorted(LEAGUE_PATHS)),
        )
        return []
    return leagues


async def _run_auto_ingest_once(leagues: list[str]) -> None:
    result = await asyncio.to_thread(sync_games_for_date, date.today(), leagues)
    logger.info(
        "Auto-ingest done: fetched=%s inserted=%s updated=%s skipped=%s errors=%s",
        result.total_fetched,
        result.inserted,
        result.updated,
        result.skipped,
        result.errors,
    )


async def _auto_ingest_loop(interval_minutes: int, leagues: list[str]) -> None:
    if interval_minutes < 1:
        logger.error("Auto-ingest interval must be >= 1 minute.")
        return
    if not leagues:
        logger.error("Auto-ingest has no valid leagues configured.")
        return

    logger.info(
        "Auto-ingest enabled: interval=%s minutes leagues=%s",
        interval_minutes,
        ",".join(leagues),
    )
    while _auto_ingest_stop and not _auto_ingest_stop.is_set():
        try:
            await _run_auto_ingest_once(leagues)
            enqueued = await asyncio.to_thread(enqueue_due_games, leagues, 2)
            if enqueued:
                logger.info("Auto-enqueue done: enqueued=%s", enqueued)
        except Exception:
            logger.exception("Auto-ingest failed.")
        try:
            await asyncio.wait_for(
                _auto_ingest_stop.wait(),
                timeout=interval_minutes * 60,
            )
        except asyncio.TimeoutError:
            continue


@app.on_event("startup")
async def start_auto_ingest() -> None:
    global _auto_ingest_task, _auto_ingest_stop, _auto_worker_task, _auto_worker_stop
    install_buffer_handler()
    logger.info("App starting up — initializing auto-ingest and worker")
    interval_minutes = int(os.getenv("AUTO_INGEST_INTERVAL_MINUTES", "15"))
    leagues_raw = os.getenv("AUTO_INGEST_LEAGUES", "NBA,NHL")
    leagues = _parse_auto_ingest_leagues(leagues_raw)
    _auto_ingest_stop = asyncio.Event()
    _auto_ingest_task = asyncio.create_task(
        _auto_ingest_loop(interval_minutes, leagues)
    )
    _auto_worker_stop = asyncio.Event()
    _auto_worker_task = asyncio.create_task(run_worker_with_shutdown(_auto_worker_stop))


@app.on_event("shutdown")
async def stop_auto_ingest() -> None:
    global _auto_ingest_task, _auto_ingest_stop, _auto_worker_task, _auto_worker_stop
    if _auto_ingest_stop:
        _auto_ingest_stop.set()
    if _auto_worker_stop:
        _auto_worker_stop.set()
    if _auto_ingest_task:
        await _auto_ingest_task
    if _auto_worker_task:
        await _auto_worker_task
    _auto_ingest_task = None
    _auto_ingest_stop = None
    _auto_worker_task = None
    _auto_worker_stop = None


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    picks = db.query(Pick).order_by(desc(Pick.created_at_utc)).limit(50).all()
    game_ids = [pick.game_id for pick in picks]
    games = (
        db.query(Game)
        .filter(Game.id.in_(game_ids))
        .order_by(Game.start_time_utc.asc())
        .all()
        if game_ids
        else []
    )
    game_lookup = {game.id: game for game in games}

    stats = {
        "total": len(picks),
        "bet": sum(1 for pick in picks if pick.result == "BET"),
        "lean": sum(1 for pick in picks if pick.result == "LEAN"),
        "no_bet": sum(1 for pick in picks if pick.result == "NO_BET"),
    }

    # Job stats for the activity log panel
    total_games = db.query(Game).count()
    jobs_queued = db.query(PickJob).filter(PickJob.status == "queued").count()
    jobs_running = db.query(PickJob).filter(PickJob.status == "running").count()
    jobs_done = db.query(PickJob).filter(PickJob.status == "done").count()
    jobs_failed = db.query(PickJob).filter(PickJob.status == "failed").count()

    job_stats = {
        "total_games": total_games,
        "queued": jobs_queued,
        "running": jobs_running,
        "done": jobs_done,
        "failed": jobs_failed,
    }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "picks": picks,
            "stats": stats,
            "games": game_lookup,
            "job_stats": job_stats,
            "active_page": "home",
        },
    )


@app.get("/ui/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    has_key = bool(settings.openai_api_key_enc)
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings,
            "has_key": has_key,
            "active_page": "settings",
        },
    )


@app.post("/ui/settings", response_class=HTMLResponse)
async def settings_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    settings = get_or_create_settings(db)
    api_key = form.get("openai_api_key", "").strip()
    if api_key:
        settings.openai_api_key_enc = encrypt_api_key(api_key)

    settings.openai_model = form.get("openai_model", settings.openai_model).strip() or "gpt-5"
    settings.openai_reasoning_effort = form.get(
        "openai_reasoning_effort", settings.openai_reasoning_effort
    ).strip() or "high"
    settings.auto_picks_concurrency = int(form.get("auto_picks_concurrency", settings.auto_picks_concurrency))
    settings.auto_picks_poll_seconds = int(form.get("auto_picks_poll_seconds", settings.auto_picks_poll_seconds))
    settings.auto_picks_max_retries = int(form.get("auto_picks_max_retries", settings.auto_picks_max_retries))
    settings.auto_picks_enabled = True
    settings.allow_totals_default = bool(form.get("allow_totals_default"))
    settings.updated_at_utc = datetime.now(timezone.utc)
    db.commit()

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings,
            "has_key": bool(settings.openai_api_key_enc),
            "saved": True,
            "active_page": "settings",
        },
    )


@app.get("/picks", response_model=list[PickOut])
def list_picks(db: Session = Depends(get_db)):
    picks = db.query(Pick).order_by(desc(Pick.created_at_utc)).all()
    return [PickOut.model_validate(pick) for pick in picks]


@app.get("/picks/{pick_id}", response_model=PickOut)
def get_pick(pick_id: int, db: Session = Depends(get_db)):
    pick = db.query(Pick).filter(Pick.id == pick_id).one_or_none()
    if not pick:
        raise HTTPException(status_code=404, detail="Pick no encontrado")
    return PickOut.model_validate(pick)


@app.api_route("/picks", methods=["POST", "PUT", "PATCH", "DELETE"])
def picks_write_blocked() -> None:
    raise HTTPException(status_code=405, detail="Manual picks are disabled")


@app.api_route("/picks/{pick_id}", methods=["PUT", "PATCH", "DELETE"])
def pick_write_blocked(pick_id: int) -> None:
    raise HTTPException(status_code=405, detail="Manual picks are disabled")


@app.get("/pick-jobs", response_model=list[PickJobOut])
def list_pick_jobs(status: str | None = None, db: Session = Depends(get_db)):
    query = db.query(PickJob).order_by(PickJob.run_at_utc.asc())
    if status:
        query = query.filter(PickJob.status == status)
    jobs = query.all()
    return [PickJobOut.model_validate(job) for job in jobs]


@app.get("/pick-jobs/{job_id}", response_model=PickJobOut)
def get_pick_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(PickJob).filter(PickJob.id == job_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Pick job no encontrado")
    return PickJobOut.model_validate(job)


@app.get("/api/games/today", response_model=GamesTodayResponse)
def api_games_today(
    league: str | None = None,
    date: str | None = None,
    db: Session = Depends(get_db),
):
    query_date = parse_query_date(date)
    start_utc, end_utc = ny_date_range_utc(query_date)

    query = db.query(Game).filter(
        Game.start_time_utc.isnot(None),
        Game.start_time_utc >= start_utc,
        Game.start_time_utc < end_utc,
    )

    normalized_league = None
    if league:
        normalized_league = league.strip().upper()
        if normalized_league:
            query = query.filter(Game.league == normalized_league)

    games = query.order_by(Game.start_time_utc.asc()).all()
    message = "No games found for requested date." if not games else None

    return GamesTodayResponse(
        games=[GameOut.model_validate(game) for game in games],
        date=query_date.isoformat(),
        league=normalized_league,
        count=len(games),
        message=message,
    )


@app.get("/api/espn/scoreboard")
def api_espn_scoreboard(
    league: str = "NBA",
    date: str | None = None,
):
    normalized_league = league.strip().upper() if league else "NBA"
    payload = fetch_scoreboard(normalized_league, date)
    if payload.get("error"):
        return payload

    events = payload.get("events") or []
    safe_dates = None
    try:
        safe_dates = normalize_dates(date)
    except ValueError:
        safe_dates = None
    return {
        "ok": True,
        "league": normalized_league,
        "dates": safe_dates,
        "count": len(events),
        "events": events,
    }


@app.get("/api/logs")
def api_logs(limit: int = 100):
    handler = get_buffer_handler()
    return {"entries": handler.entries(limit=limit)}


@app.get("/espn/scoreboard", response_class=HTMLResponse)
def espn_scoreboard_page(request: Request):
    return templates.TemplateResponse(
        "espn_scoreboard.html",
        {
            "request": request,
            "active_page": "espn",
        },
    )


def parse_query_date(value: str | None) -> date:
    if not value:
        return datetime.now(ZoneInfo("America/New_York")).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc


def ny_date_range_utc(day: date) -> tuple[datetime, datetime]:
    ny_tz = ZoneInfo("America/New_York")
    start_local = datetime.combine(day, datetime.min.time(), tzinfo=ny_tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(ZoneInfo("UTC")), end_local.astimezone(ZoneInfo("UTC"))
