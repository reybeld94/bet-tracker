from datetime import date, datetime, timedelta
import asyncio
import logging
import os
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from types import SimpleNamespace

from .db import get_db
from .ingestion.leagues import LEAGUE_PATHS
from .ingestion.sync import sync_games_for_date
from .models import Pick, Event, Game
from .schemas import GameOut, GamesTodayResponse

app = FastAPI(title="Bet Tracker (Local)")
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)
_auto_ingest_task: asyncio.Task | None = None
_auto_ingest_stop: asyncio.Event | None = None

def american_profit_units(odds: float, stake: float) -> float:
    """
    Devuelve profit en unidades (no incluye el stake de vuelta).
    Ej: stake=1u, odds=-110 => ganas 0.909u si WON
        stake=1u, odds=+120 => ganas 1.2u si WON
    """
    if odds == 0 or stake <= 0:
        return 0.0
    if odds > 0:
        return stake * (odds / 100.0)
    return stake * (100.0 / abs(odds))

def settle_pick_for_event(pick: Pick, event: Event) -> tuple[str, float] | None:
    if pick.status != "APPROVED" or pick.period != "FG":
        return None
    if event.home_score is None or event.away_score is None:
        return None

    home_score = event.home_score
    away_score = event.away_score
    market_type = pick.market_type
    side = pick.side
    line = pick.line if pick.line is not None else 0.0

    result = "PUSH"
    if market_type == "ML":
        if home_score > away_score:
            result = "WON" if side == "HOME" else "LOST"
        elif away_score > home_score:
            result = "WON" if side == "AWAY" else "LOST"
        else:
            result = "PUSH"
    elif market_type == "SPREAD":
        if side == "HOME":
            adjusted_home = home_score + line
            if adjusted_home > away_score:
                result = "WON"
            elif adjusted_home < away_score:
                result = "LOST"
            else:
                result = "PUSH"
        elif side == "AWAY":
            adjusted_away = away_score + line
            if adjusted_away > home_score:
                result = "WON"
            elif adjusted_away < home_score:
                result = "LOST"
            else:
                result = "PUSH"
    elif market_type == "TOTAL":
        total_score = home_score + away_score
        if side == "OVER":
            if total_score > line:
                result = "WON"
            elif total_score < line:
                result = "LOST"
            else:
                result = "PUSH"
        elif side == "UNDER":
            if total_score < line:
                result = "WON"
            elif total_score > line:
                result = "LOST"
            else:
                result = "PUSH"
    else:
        return None

    if result == "WON":
        profit = round(american_profit_units(pick.odds, pick.stake), 3)
    elif result == "LOST":
        profit = round(-pick.stake, 3)
    else:
        profit = 0.0

    return result, profit

def settle_event_picks(db: Session, event: Event) -> dict[str, int]:
    picks = (
        db.query(Pick)
        .filter(Pick.event_id == event.id, Pick.status == "APPROVED")
        .all()
    )
    settled = 0
    relapsed = 0
    for pick in picks:
        settlement = settle_pick_for_event(pick, event)
        if not settlement:
            continue
        if pick.result != "PENDING":
            relapsed += 1
        pick.result, pick.profit = settlement
        settled += 1
    db.commit()
    return {"settled": settled, "relapsed": relapsed}

def normalize_upper(value: str) -> str:
    return value.strip().upper()

def parse_start_time(value: str) -> datetime | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None

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
    global _auto_ingest_task, _auto_ingest_stop
    interval_minutes = int(os.getenv("AUTO_INGEST_INTERVAL_MINUTES", "15"))
    leagues_raw = os.getenv("AUTO_INGEST_LEAGUES", "NBA,NHL")
    leagues = _parse_auto_ingest_leagues(leagues_raw)
    _auto_ingest_stop = asyncio.Event()
    _auto_ingest_task = asyncio.create_task(
        _auto_ingest_loop(interval_minutes, leagues)
    )

@app.on_event("shutdown")
async def stop_auto_ingest() -> None:
    global _auto_ingest_task, _auto_ingest_stop
    if _auto_ingest_stop:
        _auto_ingest_stop.set()
    if _auto_ingest_task:
        await _auto_ingest_task
    _auto_ingest_task = None
    _auto_ingest_stop = None


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

def validate_pick_contract(
    *,
    status: str,
    event_id: int | None,
    market_type: str,
    period: str,
    side: str,
    odds: float,
    stake: float,
    recommendation: str,
    line: float | None,
) -> list[str]:
    errors: list[str] = []
    if status != "APPROVED":
        return errors

    if not event_id:
        errors.append("event_id es requerido para APPROVED")
    if not market_type:
        errors.append("market_type es requerido para APPROVED")
    if not period:
        errors.append("period es requerido para APPROVED")
    if not side:
        errors.append("side es requerido para APPROVED")
    if odds == 0:
        errors.append("odds es requerido para APPROVED")
    if stake <= 0:
        errors.append("stake es requerido para APPROVED")
    if not recommendation:
        errors.append("recommendation es requerido para APPROVED")

    if recommendation == "BET" and stake <= 0:
        errors.append("recommendation=BET requiere stake > 0")

    if market_type in {"SPREAD", "TOTAL"} and line is None:
        errors.append("market_type=SPREAD/TOTAL requiere line")
    if market_type == "ML" and line is not None:
        errors.append("market_type=ML requiere line = null")

    return errors

def parse_gpt_text(text: str) -> list[dict]:
    picks: list[dict] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines and text.strip():
        lines = [text.strip()]

    for line in lines:
        upper_line = line.upper()
        odds_match = re.search(r"([+-]\d{2,4})", upper_line)
        odds = float(odds_match.group(1)) if odds_match else 0.0

        stake_match = re.search(r"(\d+(?:\.\d+)?)\s*u\b", upper_line)
        stake = float(stake_match.group(1)) if stake_match else 1.0

        recommendation = "BET"
        for rec in ("BET", "LEAN", "PASS"):
            if rec in upper_line:
                recommendation = rec
                break

        total_match = re.search(
            r"\b(OVER|UNDER|O|U)\s*([0-9]+(?:\.[0-9]+)?)\b",
            upper_line,
        )
        market_type = "ML"
        line_value = None
        side = ""

        if total_match:
            market_type = "TOTAL"
            side = "OVER" if total_match.group(1) in {"OVER", "O"} else "UNDER"
            line_value = float(total_match.group(2))
        else:
            signed_numbers = re.findall(r"([+-]\d+(?:\.\d+)?)", upper_line)
            spread_value = None
            for number in signed_numbers:
                if odds_match and number == odds_match.group(1):
                    continue
                spread_value = float(number)
                break
            if spread_value is not None:
                market_type = "SPREAD"
                line_value = spread_value

        picks.append(
            {
                "raw_line": line,
                "market_type": market_type,
                "side": side,
                "line": line_value,
                "odds": odds,
                "stake": stake,
                "recommendation": recommendation,
            }
        )

    return picks

def match_event_for_line(line: str, events: list[Event]) -> Event | None:
    lower_line = line.lower()
    best_event = None
    best_score = 0
    for event in events:
        score = 0
        if event.home_team and event.home_team.lower() in lower_line:
            score += 1
        if event.away_team and event.away_team.lower() in lower_line:
            score += 1
        if score > best_score:
            best_event = event
            best_score = score
    return best_event if best_score > 0 else None

def infer_side_from_event(line: str, event: Event | None) -> str:
    if not event:
        return ""
    lower_line = line.lower()
    if event.home_team and event.home_team.lower() in lower_line:
        return "HOME"
    if event.away_team and event.away_team.lower() in lower_line:
        return "AWAY"
    return ""

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    picks = (
        db.query(Pick)
        .options(joinedload(Pick.event))
        .order_by(desc(Pick.created_at))
        .limit(100)
        .all()
    )
    events = db.query(Event).order_by(desc(Event.start_time)).limit(100).all()

    approved_query = db.query(Pick).filter(Pick.status == "APPROVED")
    total = approved_query.count()
    won = approved_query.filter(Pick.result == "WON").count()
    lost = approved_query.filter(Pick.result == "LOST").count()
    push = approved_query.filter(Pick.result == "PUSH").count()
    pending = approved_query.filter(Pick.result == "PENDING").count()

    profit = approved_query.with_entities(Pick.profit).all()
    total_profit = round(sum([p[0] for p in profit]), 3) if profit else 0.0

    decided = won + lost + push
    winrate = round((won / (won + lost)) * 100, 1) if (won + lost) > 0 else 0.0

    stats = {
        "total": total,
        "won": won,
        "lost": lost,
        "push": push,
        "pending": pending,
        "winrate": winrate,
        "units": total_profit,
        "decided": decided,
    }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "picks": picks,
            "stats": stats,
            "events": events,
        },
    )

@app.get("/events/new", response_class=HTMLResponse)
def new_event(request: Request):
    return templates.TemplateResponse("event_form.html", {"request": request})

@app.get("/ingest", response_class=HTMLResponse)
def ingest_form(
    request: Request,
    sport: str = "",
    league: str = "",
    db: Session = Depends(get_db),
):
    now = datetime.now()
    start_day = datetime(now.year, now.month, now.day)
    end_day = start_day + timedelta(days=1)
    base_query = db.query(Event).filter(
        Event.start_time.isnot(None),
        Event.start_time >= start_day,
        Event.start_time < end_day,
    )

    sports = [
        row[0]
        for row in base_query.with_entities(Event.sport).distinct().all()
        if row[0]
    ]
    leagues = [
        row[0]
        for row in base_query.with_entities(Event.league).distinct().all()
        if row[0]
    ]

    return templates.TemplateResponse(
        "ingest.html",
        {
            "request": request,
            "text": "",
            "picks": [],
            "events": [],
            "sports": sorted(sports),
            "leagues": sorted(leagues),
            "selected_sport": sport.strip(),
            "selected_league": league.strip(),
            "gpt_name": "",
            "source": "AI",
            "errors": [],
        },
    )

@app.post("/ingest", response_class=HTMLResponse)
def ingest_parse(
    request: Request,
    text: str = Form(""),
    sport: str = Form(""),
    league: str = Form(""),
    gpt_name: str = Form(""),
    source: str = Form("AI"),
    db: Session = Depends(get_db),
):
    now = datetime.now()
    start_day = datetime(now.year, now.month, now.day)
    end_day = start_day + timedelta(days=1)

    base_query = db.query(Event).filter(
        Event.start_time.isnot(None),
        Event.start_time >= start_day,
        Event.start_time < end_day,
    )

    sport_filter = sport.strip()
    league_filter = league.strip()
    filtered_query = base_query
    if sport_filter:
        filtered_query = filtered_query.filter(Event.sport == sport_filter)
    if league_filter:
        filtered_query = filtered_query.filter(Event.league == league_filter)

    events = filtered_query.order_by(Event.start_time.asc()).all()
    sports = [
        row[0]
        for row in base_query.with_entities(Event.sport).distinct().all()
        if row[0]
    ]
    leagues = [
        row[0]
        for row in base_query.with_entities(Event.league).distinct().all()
        if row[0]
    ]

    parsed_picks = parse_gpt_text(text)
    picks: list[SimpleNamespace] = []
    for pick in parsed_picks:
        event = match_event_for_line(pick["raw_line"], events)
        side = pick["side"]
        if pick["market_type"] != "TOTAL":
            side = infer_side_from_event(pick["raw_line"], event)
        error_message = "" if event else "Needs event"
        picks.append(
            SimpleNamespace(
                raw_line=pick["raw_line"],
                market_type=pick["market_type"],
                side=side,
                line=pick["line"],
                odds=pick["odds"],
                stake=pick["stake"],
                recommendation=pick["recommendation"],
                event_id=event.id if event else None,
                event_label=(
                    f"{event.home_team} vs {event.away_team}" if event else ""
                ),
                error=error_message,
            )
        )

    return templates.TemplateResponse(
        "ingest.html",
        {
            "request": request,
            "text": text,
            "picks": picks,
            "events": events,
            "sports": sorted(sports),
            "leagues": sorted(leagues),
            "selected_sport": sport_filter,
            "selected_league": league_filter,
            "gpt_name": gpt_name,
            "source": source.strip() or "AI",
            "errors": [],
        },
    )

@app.post("/ingest/create")
async def ingest_create(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    pick_count = int(form.get("pick_count", 0))
    gpt_name = form.get("gpt_name", "").strip()
    source = form.get("source", "AI").strip() or "AI"
    created_ids: list[int] = []

    for index in range(pick_count):
        prefix = f"pick-{index}-"
        event_id_value = form.get(f"{prefix}event_id", "").strip()
        parsed_event_id = int(event_id_value) if event_id_value else None
        market_type = normalize_upper(form.get(f"{prefix}market_type", ""))
        period = normalize_upper(form.get(f"{prefix}period", "FG")) or "FG"
        side = normalize_upper(form.get(f"{prefix}side", ""))
        recommendation = normalize_upper(
            form.get(f"{prefix}recommendation", "BET")
        )
        line_value = form.get(f"{prefix}line", "").strip()
        odds_value = form.get(f"{prefix}odds", "0").strip()
        stake_value = form.get(f"{prefix}stake", "1").strip()
        reasoning = form.get(f"{prefix}reasoning", "").strip()

        parsed_line = float(line_value) if line_value else None
        odds = float(odds_value) if odds_value else 0.0
        stake = float(stake_value) if stake_value else 1.0

        pick = Pick(
            event_id=parsed_event_id,
            sportsbook="",
            market_type=market_type,
            period=period,
            line=parsed_line,
            side=side,
            odds=odds,
            stake=stake,
            recommendation=recommendation,
            status="DRAFT",
            source=source,
            gpt_name=gpt_name,
            reasoning=reasoning,
            result="PENDING",
            profit=0.0,
        )
        db.add(pick)
        db.flush()
        created_ids.append(pick.id)

    db.commit()
    if created_ids:
        return RedirectResponse(
            url=f"/picks/{created_ids[-1]}", status_code=303
        )
    return RedirectResponse(url="/", status_code=303)

@app.get("/events/today", response_class=HTMLResponse)
def events_today(
    request: Request,
    sport: str = "",
    league: str = "",
    db: Session = Depends(get_db),
):
    now = datetime.now()
    start_day = datetime(now.year, now.month, now.day)
    end_day = start_day + timedelta(days=1)

    base_query = db.query(Event).filter(
        Event.start_time.isnot(None),
        Event.start_time >= start_day,
        Event.start_time < end_day,
    )

    sport_filter = sport.strip()
    league_filter = league.strip()

    filtered_query = base_query
    if sport_filter:
        filtered_query = filtered_query.filter(Event.sport == sport_filter)
    if league_filter:
        filtered_query = filtered_query.filter(Event.league == league_filter)

    events = filtered_query.order_by(Event.start_time.asc()).all()
    sports = [
        row[0]
        for row in base_query.with_entities(Event.sport).distinct().all()
        if row[0]
    ]
    leagues = [
        row[0]
        for row in base_query.with_entities(Event.league).distinct().all()
        if row[0]
    ]

    return templates.TemplateResponse(
        "events_today.html",
        {
            "request": request,
            "events": events,
            "sports": sorted(sports),
            "leagues": sorted(leagues),
            "selected_sport": sport_filter,
            "selected_league": league_filter,
            "start_day": start_day,
        },
    )


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

@app.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(
    request: Request,
    event_id: int,
    warning: str = "",
    db: Session = Depends(get_db),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event no encontrado")
    picks = (
        db.query(Pick)
        .filter(Pick.event_id == event.id)
        .order_by(desc(Pick.created_at))
        .all()
    )
    return templates.TemplateResponse(
        "event_detail.html",
        {
            "request": request,
            "event": event,
            "picks": picks,
            "warning": warning,
        },
    )

@app.post("/events/{event_id}/final")
def set_event_final(
    event_id: int,
    home_score: int = Form(...),
    away_score: int = Form(...),
    db: Session = Depends(get_db),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event no encontrado")

    score_changed = (
        event.home_score != home_score or event.away_score != away_score
    )
    event.home_score = home_score
    event.away_score = away_score
    event.status = "FINAL"
    db.commit()

    settlement = settle_event_picks(db, event)
    warning = ""
    if settlement["relapsed"] > 0 or score_changed:
        warning = (
            "Re-liquidación ejecutada: "
            f"{settlement['settled']} picks, "
            f"{settlement['relapsed']} ya tenían resultado."
        )
    return RedirectResponse(
        url=f"/events/{event.id}?warning={quote(warning)}", status_code=303
    )

@app.get("/picks/new", response_class=HTMLResponse)
def new_pick(
    request: Request,
    event_id: int | None = None,
    db: Session = Depends(get_db),
):
    events = db.query(Event).order_by(desc(Event.start_time)).limit(200).all()
    selected_event = None
    if event_id:
        selected_event = db.query(Event).filter(Event.id == event_id).first()
    return templates.TemplateResponse(
        "pick_form.html",
        {
            "request": request,
            "events": events,
            "selected_event": selected_event,
            "errors": [],
            "pick": None,
        },
    )

@app.post("/events/create")
def create_event(
    sport: str = Form(""),
    league: str = Form(""),
    home_team: str = Form(""),
    away_team: str = Form(""),
    start_time: str = Form(""),
    status: str = Form("SCHEDULED"),
    db: Session = Depends(get_db),
):
    status_value = normalize_upper(status) or "SCHEDULED"
    parsed_start_time = parse_start_time(start_time)
    event = Event(
        sport=sport.strip(),
        league=league.strip(),
        home_team=home_team.strip(),
        away_team=away_team.strip(),
        start_time=parsed_start_time,
        status=status_value,
    )
    db.add(event)
    db.commit()
    return RedirectResponse(url="/events/today", status_code=303)

@app.post("/picks/create")
def create_pick(
    request: Request,
    event_id: str = Form(""),
    sportsbook: str = Form(""),
    market_type: str = Form(""),
    period: str = Form("FG"),
    line: str = Form(""),
    side: str = Form(""),
    odds: float = Form(0.0),
    stake: float = Form(0.0),
    recommendation: str = Form(""),
    status: str = Form("DRAFT"),
    source: str = Form("AI"),
    gpt_name: str = Form(""),
    reasoning: str = Form(""),
    db: Session = Depends(get_db),
):
    normalized_status = normalize_upper(status) or "DRAFT"
    normalized_market = normalize_upper(market_type)
    normalized_side = normalize_upper(side)
    normalized_recommendation = normalize_upper(recommendation)
    normalized_period = normalize_upper(period) or "FG"
    parsed_event_id = int(event_id) if event_id.strip() else None
    parsed_line = float(line) if line.strip() else None
    errors = validate_pick_contract(
        status=normalized_status,
        event_id=parsed_event_id,
        market_type=normalized_market,
        period=normalized_period,
        side=normalized_side,
        odds=float(odds),
        stake=float(stake),
        recommendation=normalized_recommendation,
        line=parsed_line,
    )
    if errors:
        events = db.query(Event).order_by(desc(Event.start_time)).limit(200).all()
        selected_event = None
        if parsed_event_id:
            selected_event = db.query(Event).filter(Event.id == parsed_event_id).first()
        pick_preview = SimpleNamespace(
            event_id=parsed_event_id,
            sportsbook=sportsbook.strip(),
            market_type=normalized_market,
            period=normalized_period,
            line=parsed_line,
            side=normalized_side,
            odds=float(odds),
            stake=float(stake),
            recommendation=normalized_recommendation,
            status=normalized_status,
            source=source.strip() or "AI",
            gpt_name=gpt_name.strip(),
            reasoning=reasoning.strip(),
        )
        return templates.TemplateResponse(
            "pick_form.html",
            {
                "request": request,
                "events": events,
                "selected_event": selected_event,
                "pick": pick_preview,
                "errors": errors,
            },
            status_code=400,
        )

    pick = Pick(
        event_id=parsed_event_id,
        sportsbook=sportsbook.strip(),
        market_type=normalized_market,
        period=normalized_period,
        line=parsed_line,
        side=normalized_side,
        odds=float(odds),
        stake=float(stake),
        recommendation=normalized_recommendation,
        status=normalized_status,
        source=source.strip() or "AI",
        gpt_name=gpt_name.strip(),
        reasoning=reasoning.strip(),
        result="PENDING",
        profit=0.0,
    )
    db.add(pick)
    db.commit()
    return RedirectResponse(url=f"/picks/{pick.id}", status_code=303)

@app.get("/picks/{pick_id}", response_class=HTMLResponse)
def pick_detail(
    request: Request,
    pick_id: int,
    db: Session = Depends(get_db),
):
    pick = (
        db.query(Pick)
        .options(joinedload(Pick.event))
        .filter(Pick.id == pick_id)
        .first()
    )
    if not pick:
        raise HTTPException(status_code=404, detail="Pick no encontrado")
    return templates.TemplateResponse(
        "pick_detail.html",
        {"request": request, "pick": pick, "errors": []},
    )

@app.get("/picks/{pick_id}/edit", response_class=HTMLResponse)
def edit_pick(
    request: Request,
    pick_id: int,
    db: Session = Depends(get_db),
):
    pick = db.query(Pick).filter(Pick.id == pick_id).first()
    if not pick:
        raise HTTPException(status_code=404, detail="Pick no encontrado")
    events = db.query(Event).order_by(desc(Event.start_time)).limit(200).all()
    return templates.TemplateResponse(
        "pick_form.html",
        {
            "request": request,
            "events": events,
            "selected_event": pick.event,
            "pick": pick,
            "errors": [],
        },
    )

@app.post("/picks/{pick_id}/update")
def update_pick(
    request: Request,
    pick_id: int,
    event_id: str = Form(""),
    sportsbook: str = Form(""),
    market_type: str = Form(""),
    period: str = Form("FG"),
    line: str = Form(""),
    side: str = Form(""),
    odds: float = Form(0.0),
    stake: float = Form(0.0),
    recommendation: str = Form(""),
    status: str = Form("DRAFT"),
    source: str = Form("AI"),
    gpt_name: str = Form(""),
    reasoning: str = Form(""),
    db: Session = Depends(get_db),
):
    pick = db.query(Pick).filter(Pick.id == pick_id).first()
    if not pick:
        raise HTTPException(status_code=404, detail="Pick no encontrado")

    normalized_status = normalize_upper(status) or "DRAFT"
    normalized_market = normalize_upper(market_type)
    normalized_side = normalize_upper(side)
    normalized_recommendation = normalize_upper(recommendation)
    normalized_period = normalize_upper(period) or "FG"
    parsed_event_id = int(event_id) if event_id.strip() else None
    parsed_line = float(line) if line.strip() else None
    errors = validate_pick_contract(
        status=normalized_status,
        event_id=parsed_event_id,
        market_type=normalized_market,
        period=normalized_period,
        side=normalized_side,
        odds=float(odds),
        stake=float(stake),
        recommendation=normalized_recommendation,
        line=parsed_line,
    )
    if errors:
        events = db.query(Event).order_by(desc(Event.start_time)).limit(200).all()
        selected_event = None
        if parsed_event_id:
            selected_event = db.query(Event).filter(Event.id == parsed_event_id).first()
        pick_preview = SimpleNamespace(
            event_id=parsed_event_id,
            sportsbook=sportsbook.strip(),
            market_type=normalized_market,
            period=normalized_period,
            line=parsed_line,
            side=normalized_side,
            odds=float(odds),
            stake=float(stake),
            recommendation=normalized_recommendation,
            status=normalized_status,
            source=source.strip() or "AI",
            gpt_name=gpt_name.strip(),
            reasoning=reasoning.strip(),
        )
        return templates.TemplateResponse(
            "pick_form.html",
            {
                "request": request,
                "events": events,
                "selected_event": selected_event,
                "pick": pick_preview,
                "errors": errors,
            },
            status_code=400,
        )

    pick.event_id = parsed_event_id
    pick.sportsbook = sportsbook.strip()
    pick.market_type = normalized_market
    pick.period = normalized_period
    pick.line = parsed_line
    pick.side = normalized_side
    pick.odds = float(odds)
    pick.stake = float(stake)
    pick.recommendation = normalized_recommendation
    pick.status = normalized_status
    pick.source = source.strip() or "AI"
    pick.gpt_name = gpt_name.strip()
    pick.reasoning = reasoning.strip()
    db.commit()
    return RedirectResponse(url=f"/picks/{pick.id}", status_code=303)

@app.post("/picks/{pick_id}/approve")
def approve_pick(
    request: Request,
    pick_id: int,
    db: Session = Depends(get_db),
):
    pick = (
        db.query(Pick)
        .options(joinedload(Pick.event))
        .filter(Pick.id == pick_id)
        .first()
    )
    if not pick:
        raise HTTPException(status_code=404, detail="Pick no encontrado")

    errors = validate_pick_contract(
        status="APPROVED",
        event_id=pick.event_id,
        market_type=pick.market_type,
        period=pick.period,
        side=pick.side,
        odds=pick.odds,
        stake=pick.stake,
        recommendation=pick.recommendation,
        line=pick.line,
    )
    if errors:
        return templates.TemplateResponse(
            "pick_detail.html",
            {"request": request, "pick": pick, "errors": errors},
            status_code=400,
        )

    pick.status = "APPROVED"
    db.commit()
    return RedirectResponse(url=f"/picks/{pick.id}", status_code=303)

@app.post("/picks/{pick_id}/set_result")
def set_result(
    pick_id: int,
    result: str = Form(...),
    db: Session = Depends(get_db),
):
    pick = db.query(Pick).filter(Pick.id == pick_id).first()
    if not pick:
        return RedirectResponse(url="/", status_code=303)

    result = result.upper().strip()
    pick.result = result

    if result == "WON":
        pick.profit = round(american_profit_units(pick.odds, pick.stake), 3)
    elif result == "LOST":
        pick.profit = round(-pick.stake, 3)
    elif result == "PUSH":
        pick.profit = 0.0
    else:  # PENDING o cualquier cosa rara
        pick.result = "PENDING"
        pick.profit = 0.0

    db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.post("/picks/{pick_id}/delete")
def delete_pick(pick_id: int, db: Session = Depends(get_db)):
    pick = db.query(Pick).filter(Pick.id == pick_id).first()
    if pick:
        db.delete(pick)
        db.commit()
    return RedirectResponse(url="/", status_code=303)
