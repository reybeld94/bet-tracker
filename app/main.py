from fastapi import FastAPI, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from .db import get_db
from .models import Pick

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

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    picks = db.query(Pick).order_by(desc(Pick.created_at)).limit(100).all()

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
    })

@app.post("/picks/create")
def create_pick(
    sport: str = Form(""),
    event: str = Form(""),
    market: str = Form(""),
    selection: str = Form(""),
    odds: float = Form(0.0),
    stake: float = Form(1.0),
    source: str = Form("AI"),
    gpt_name: str = Form(""),
    reasoning: str = Form(""),
    db: Session = Depends(get_db),
):
    pick = Pick(
        sport=sport.strip(),
        event=event.strip(),
        market=market.strip(),
        selection=selection.strip(),
        odds=float(odds),
        stake=float(stake),
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
