from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import asyncio
import json
import logging
import os
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.ai.openai_client import OpenAIClientError, request_pick
from app.db import get_db
from app.ingestion.espn_client import fetch_scoreboard, normalize_dates
from app.ingestion.leagues import LEAGUE_PATHS
from app.ingestion.espn_parser import parse_scoreboard
from app.ingestion.sync import sync_games_for_date
from app.log_buffer import install_buffer_handler, get_buffer_handler
from app.models import Game, Pick, PickJob
from app.picks.enqueue import enqueue_due_games
from app.picks.payload import build_game_payload
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

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "picks": picks,
            "stats": stats,
            "games": game_lookup,
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


@app.get("/api/espn/events")
def api_espn_events(league: str = "NBA", date: str | None = None):
    normalized_league = league.strip().upper() if league else "NBA"
    payload = fetch_scoreboard(normalized_league, date)
    if payload.get("error"):
        return {
            "ok": False,
            "league": normalized_league,
            "error": payload.get("error"),
            "details": payload,
            "events": [],
        }

    events = _scoreboard_events(payload, normalized_league)
    return {
        "ok": True,
        "league": normalized_league,
        "count": len(events),
        "events": events,
    }


@app.post("/api/ai/analyze-event")
def api_ai_analyze_event(payload: dict, db: Session = Depends(get_db)):
    event = payload.get("event")
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="'event' is required")

    settings = get_or_create_settings(db)
    game_stub = SimpleNamespace(
        sport=event.get("sport") or "basketball",
        league=(event.get("league") or "").upper(),
        home_team=event.get("home_team") or "TBD",
        away_team=event.get("away_team") or "TBD",
        start_time_utc=_parse_event_start(event.get("start_time_utc")),
    )
    ai_payload = build_game_payload(game_stub, settings)
    ai_payload["provider_event_id"] = event.get("provider_event_id")

    try:
        ai_result, raw_ai_json = request_pick(ai_payload, settings)
    except OpenAIClientError as exc:
        return {
            "ok": False,
            "event": event,
            "message": str(exc),
            "analysis_type": "error",
        }

    picks: list[dict] = []
    message = ""
    analysis_type = "picks"

    if isinstance(ai_result, dict) and isinstance(ai_result.get("picks"), list):
        picks = [pick for pick in ai_result["picks"] if isinstance(pick, dict)]
    elif isinstance(ai_result, dict) and "result" in ai_result:
        picks = [ai_result]
    else:
        analysis_type = "non_pick"
        message = "La IA respondio un formato distinto a picks."

    return {
        "ok": True,
        "event": event,
        "analysis_type": analysis_type,
        "message": message,
        "picks": picks,
        "raw_result": ai_result,
        "raw_ai_json": raw_ai_json,
    }


@app.post("/api/picks/save")
def api_save_pick(payload: dict, db: Session = Depends(get_db)):
    event = payload.get("event")
    pick_payload = payload.get("pick")
    raw_ai_json = payload.get("raw_ai_json") or ""

    if not isinstance(event, dict) or not isinstance(pick_payload, dict):
        raise HTTPException(status_code=400, detail="'event' and 'pick' are required")

    provider_event_id = str(event.get("provider_event_id") or "").strip()
    if not provider_event_id:
        raise HTTPException(status_code=400, detail="event.provider_event_id is required")

    required_pick_fields = {
        "result", "market", "emoji", "selection", "line", "odds_format", "odds",
        "p_est", "p_implied", "ev", "confidence", "stake_u", "high_prob_low_payout",
        "is_value", "reasons", "risks", "triggers", "missing_data", "as_of_utc", "notes",
    }
    missing = sorted(required_pick_fields - set(pick_payload.keys()))
    if missing:
        raise HTTPException(status_code=400, detail=f"pick missing fields: {', '.join(missing)}")

    game = db.query(Game).filter(
        Game.provider == "espn",
        Game.provider_event_id == provider_event_id,
    ).one_or_none()

    now_utc = datetime.now(timezone.utc)
    if not game:
        game = Game(
            provider="espn",
            provider_event_id=provider_event_id,
            sport=str(event.get("sport") or ""),
            league=str(event.get("league") or "").upper(),
            start_time_utc=_parse_event_start(event.get("start_time_utc")),
            status=str(event.get("status") or "scheduled"),
            home_team=str(event.get("home_team") or "TBD"),
            away_team=str(event.get("away_team") or "TBD"),
            raw_json=json.dumps(event, ensure_ascii=False),
        )
        db.add(game)
        db.flush()

    pick = db.query(Pick).filter(Pick.game_id == game.id).one_or_none()
    if not pick:
        pick = Pick(game_id=game.id, created_at_utc=now_utc)
        db.add(pick)

    pick.result = pick_payload["result"]
    pick.market = pick_payload["market"]
    pick.emoji = pick_payload["emoji"]
    pick.selection = pick_payload["selection"]
    pick.line = pick_payload["line"]
    pick.odds_format = pick_payload["odds_format"]
    pick.odds = pick_payload["odds"]
    pick.p_est = pick_payload["p_est"]
    pick.p_implied = pick_payload["p_implied"]
    pick.ev = pick_payload["ev"]
    pick.confidence = pick_payload["confidence"]
    pick.stake_u = pick_payload["stake_u"]
    pick.high_prob_low_payout = pick_payload["high_prob_low_payout"]
    pick.is_value = pick_payload["is_value"]
    pick.reasons_json = json.dumps(pick_payload["reasons"], ensure_ascii=False)
    pick.risks_json = json.dumps(pick_payload["risks"], ensure_ascii=False)
    pick.triggers_json = json.dumps(pick_payload["triggers"], ensure_ascii=False)
    pick.missing_data_json = json.dumps(pick_payload["missing_data"], ensure_ascii=False)
    pick.as_of_utc = pick_payload["as_of_utc"]
    pick.notes = pick_payload["notes"]
    pick.raw_ai_json = raw_ai_json
    pick.updated_at_utc = now_utc
    db.commit()

    return {
        "ok": True,
        "pick_id": pick.id,
        "game_id": game.id,
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


def _parse_event_start(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _scoreboard_events(payload: dict, league: str) -> list[dict]:
    parsed_games = parse_scoreboard(payload, league)
    events: list[dict] = []
    for game in parsed_games:
        events.append(
            {
                "provider_event_id": game.provider_event_id,
                "sport": game.sport,
                "league": game.league,
                "home_team": game.home_team_name,
                "away_team": game.away_team_name,
                "status": game.status,
                "start_time_utc": game.start_time_utc.isoformat() if game.start_time_utc else None,
            }
        )
    return events
