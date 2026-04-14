"""
XSMN Lottery Limit Management System - API Server.

FastAPI server providing REST APIs for:
- Lottery results browsing
- Bet limit management (100 lô numbers)
- Profit/Loss statistics
- Data scraping triggers
"""

import os
import sys
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (
    init_db, get_all_lo_status, get_lo_status, get_results_for_date,
    get_results_history, get_scraped_dates, cleanup_old_data,
    get_connection
)
from scraper import scrape_today, scrape_last_n_days, scrape_day
from limit_engine import (
    get_limit_summary, get_consecutive_los, update_all_lo_status,
    recalculate_all_from_history, POINT_VALUE, WIN_MULTIPLIER,
    BASE_LIMIT_SCHEDULE, CONSECUTIVE_LIMITS, MIN_LIMIT
)
from profit_calculator import (
    calculate_period_profit, get_lo_profit_breakdown,
    get_profit_chart_data, simulate_bets_for_date
)


# ═══════════════════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    print("[*] Starting XSMN Lottery Limit System...")
    init_db()
    print("[OK] Database ready")
    yield
    print("[*] Shutting down...")


app = FastAPI(
    title="XSMN Lottery Limit System",
    description="Hệ thống quản lý hạn mức lô đề Xổ Số Miền Nam",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frontend')
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ═══════════════════════════════════════════════════════════
# FRONTEND ROUTES
# ═══════════════════════════════════════════════════════════

@app.get("/")
async def serve_frontend():
    """Serve the main dashboard page."""
    index_path = os.path.join(FRONTEND_DIR, 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Frontend not found. Please create frontend/index.html"}


# ═══════════════════════════════════════════════════════════
# API ROUTES - LIMITS
# ═══════════════════════════════════════════════════════════

@app.get("/api/limits")
async def get_limits():
    """Get current limit status for all 100 lô numbers (00-99)."""
    try:
        summary = get_limit_summary()
        return {
            "status": "success",
            "data": summary,
            "config": {
                "point_value": POINT_VALUE,
                "win_multiplier": WIN_MULTIPLIER,
                "min_limit": MIN_LIMIT,
                "base_schedule": BASE_LIMIT_SCHEDULE,
                "consecutive_limits": CONSECUTIVE_LIMITS,
            },
            "updated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/limits/{lo_number}")
async def get_limit_detail(lo_number: str):
    """Get detailed limit info for a specific lô number."""
    if not lo_number.isdigit() or len(lo_number) != 2:
        raise HTTPException(status_code=400, detail="Lô number must be 2 digits (00-99)")

    status = get_lo_status(lo_number)
    if not status:
        raise HTTPException(status_code=404, detail=f"Lô {lo_number} not found")

    # Get recent history
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT date, count FROM lo_daily 
        WHERE lo_number = ? 
        ORDER BY date DESC LIMIT 30
    ''', (lo_number,))
    history = [dict(row) for row in cursor.fetchall()]

    # Get bet history
    cursor.execute('''
        SELECT date, bet_amount, is_win, profit 
        FROM bet_history 
        WHERE lo_number = ? 
        ORDER BY date DESC LIMIT 30
    ''', (lo_number,))
    bets = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return {
        "status": "success",
        "data": {
            **status,
            "history": history,
            "bet_history": bets,
        }
    }


@app.get("/api/consecutive")
async def get_consecutive():
    """Get list of lô numbers currently on consecutive streaks."""
    try:
        data = get_consecutive_los()
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# API ROUTES - RESULTS
# ═══════════════════════════════════════════════════════════

@app.get("/api/results/today")
async def get_today_results():
    """Get today's lottery results."""
    today = datetime.now().strftime('%Y-%m-%d')
    results = get_results_for_date(today)

    if not results:
        # Try yesterday if today's not available
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        results = get_results_for_date(yesterday)
        if results:
            return {"status": "success", "date": yesterday, "data": results,
                    "note": "Showing yesterday's results (today not available yet)"}
        return {"status": "success", "date": today, "data": [],
                "note": "No results available yet"}

    return {"status": "success", "date": today, "data": results}


@app.get("/api/results/date/{date_str}")
async def get_results_by_date(date_str: str):
    """Get lottery results for a specific date (format: YYYY-MM-DD)."""
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    results = get_results_for_date(date_str)
    return {"status": "success", "date": date_str, "data": results}


@app.get("/api/results/history")
async def get_history(days: int = Query(default=30, ge=1, le=90)):
    """Get lottery results history for the last N days."""
    history = get_results_history(days)

    # Group by date
    by_date = {}
    for record in history:
        date = record['date']
        if date not in by_date:
            by_date[date] = []
        by_date[date].append({
            'lo_number': record['lo_number'],
            'count': record['total_count']
        })

    return {"status": "success", "days": days, "data": by_date}


@app.get("/api/results/lo-daily")
async def get_lo_daily_history(days: int = Query(default=30, ge=1, le=90)):
    """Get daily lô appearance data for heat map / tracking."""
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT date, lo_number, count 
        FROM lo_daily 
        WHERE date >= ?
        ORDER BY date DESC, lo_number ASC
    ''', (cutoff,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {"status": "success", "data": rows}


# ═══════════════════════════════════════════════════════════
# API ROUTES - STATISTICS / PROFIT
# ═══════════════════════════════════════════════════════════

@app.get("/api/stats/profit")
async def get_profit_stats(days: int = Query(default=30, ge=1, le=90)):
    """Get profit/loss statistics for the last N days."""
    try:
        stats = calculate_period_profit(days)
        return {"status": "success", "data": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/profit/chart")
async def get_profit_chart(days: int = Query(default=30, ge=1, le=90)):
    """Get profit chart data for Chart.js visualization."""
    try:
        chart_data = get_profit_chart_data(days)
        return {"status": "success", "data": chart_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/lo-breakdown")
async def get_lo_breakdown(days: int = Query(default=30, ge=1, le=90)):
    """Get profit breakdown per lô number."""
    try:
        breakdown = get_lo_profit_breakdown(days)
        return {"status": "success", "data": breakdown}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# API ROUTES - SCRAPING / DATA MANAGEMENT
# ═══════════════════════════════════════════════════════════

@app.post("/api/scrape/today")
async def trigger_scrape_today(background_tasks: BackgroundTasks):
    """Trigger scraping of today's results."""
    background_tasks.add_task(_scrape_and_update_today)
    return {"status": "started", "message": "Scraping today's results in background..."}


@app.post("/api/scrape/range")
async def trigger_scrape_range(
    days: int = Query(default=30, ge=1, le=90),
    background_tasks: BackgroundTasks = None
):
    """Trigger scraping of the last N days."""
    background_tasks.add_task(_scrape_and_update_range, days)
    return {
        "status": "started",
        "message": f"Scraping last {days} days in background. This may take a few minutes..."
    }


@app.post("/api/recalculate")
async def trigger_recalculate(background_tasks: BackgroundTasks):
    """Recalculate all lô statuses from stored history."""
    background_tasks.add_task(recalculate_all_from_history)
    return {"status": "started", "message": "Recalculating all limits from history..."}


@app.get("/api/scrape/status")
async def get_scrape_status():
    """Get list of scraped dates."""
    dates = get_scraped_dates()
    return {
        "status": "success",
        "scraped_dates": dates,
        "total_days": len(dates),
        "latest": dates[0] if dates else None,
    }


@app.post("/api/cleanup")
async def trigger_cleanup(days: int = Query(default=30)):
    """Clean up data older than N days."""
    deleted = cleanup_old_data(days)
    return {"status": "success", "deleted_records": deleted}


# ═══════════════════════════════════════════════════════════
# BACKGROUND TASKS
# ═══════════════════════════════════════════════════════════

def _scrape_and_update_today():
    """Background task: scrape today and update limits."""
    try:
        result = scrape_today()
        if result:
            today = datetime.now().strftime('%Y-%m-%d')
            update_all_lo_status(today)
            print(f"[OK] Scraped and updated for today ({today})")
        else:
            print("[WARN] No results found for today")
    except Exception as e:
        print(f"[ERR] Error scraping today: {e}")


def _scrape_and_update_range(days: int):
    """Background task: scrape range and recalculate all limits."""
    try:
        count = scrape_last_n_days(days, delay=1.5)
        if count > 0:
            recalculate_all_from_history()
            print(f"[OK] Scraped {count} days and recalculated all limits")
        else:
            print("[WARN] No days were scraped")
    except Exception as e:
        print(f"[ERR] Error scraping range: {e}")


# ═══════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    import uvicorn
    print("=" * 60)
    print("   XSMN LOTTERY LIMIT MANAGEMENT SYSTEM")
    print("   http://localhost:8000")
    print("=" * 60)
    uvicorn.run("main:app", host="0.0.0.0", port=8899, reload=True)
