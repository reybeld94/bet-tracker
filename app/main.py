from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from types import SimpleNamespace

from .db import get_db
from .models import Pick, Event

app = FastAPI(title="Bet Tracker (Local)")
templates = Jinja2Templates(directory="app/templates")

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

    total = db.query(Pick).count()
    won = db.query(Pick).filter(Pick.result == "WON").count()
    lost = db.query(Pick).filter(Pick.result == "LOST").count()
    push = db.query(Pick).filter(Pick.result == "PUSH").count()
    pending = db.query(Pick).filter(Pick.result == "PENDING").count()

    profit = db.query(Pick).with_entities(Pick.profit).all()
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
