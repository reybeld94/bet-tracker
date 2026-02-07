from datetime import datetime

from fastapi import FastAPI, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc

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

    return templates.TemplateResponse("index.html", {
        "request": request,
        "picks": picks,
        "stats": stats,
        "events": events,
    })

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
    return RedirectResponse(url="/", status_code=303)

@app.post("/picks/create")
def create_pick(
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
        raise HTTPException(status_code=400, detail=errors)

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
    return RedirectResponse(url="/", status_code=303)

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
