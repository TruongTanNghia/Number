"""
Lottery Limit Management System - API Server.
Supports 3 regions: XSMN (Miền Nam), XSMB (Miền Bắc), XSMT (Miền Trung).

FastAPI server providing REST APIs for:
- Lottery results browsing (all 3 regions)
- Bet limit management (100 lô numbers per region)
- Profit/Loss statistics per region
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
    get_connection, VALID_REGIONS
)
from scraper import (
    scrape_today, scrape_last_n_days, scrape_day,
    scrape_all_regions_range
)
from limit_engine import (
    get_limit_summary, get_consecutive_los, update_all_lo_status,
    recalculate_all_from_history, POINT_VALUE, WIN_MULTIPLIER,
    BASE_LIMIT_SCHEDULE, CONSECUTIVE_LIMITS, MIN_LIMIT,
    PRICE_PER_POINT, COST_MULTIPLIER,
)
from profit_calculator import (
    calculate_period_profit, get_lo_profit_breakdown,
    get_profit_chart_data, simulate_bets_for_date
)
from prediction import predict as run_prediction


# ═══════════════════════════════════════════════════════════
# APP SETUP
# ═══════════════════════════════════════════════════════════

REGION_LABELS = {
    'xsmn': 'Xổ Số Miền Nam',
    'xsmb': 'Xổ Số Miền Bắc',
    'xsmt': 'Xổ Số Miền Trung',
}

def _validate_region(region: str) -> str:
    """Validate and normalize region parameter."""
    region = region.lower().strip()
    if region not in VALID_REGIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid region '{region}'. Must be one of: {', '.join(VALID_REGIONS)}"
        )
    return region


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    print("[*] Starting Lottery Limit System (3 Mien)...")
    init_db()
    print("[OK] Database ready (XSMN + XSMB + XSMT)")
    yield
    print("[*] Shutting down...")


app = FastAPI(
    title="Lottery Limit System - 3 Miền",
    description="He thong quan ly han muc lo de Xo So 3 Mien (Nam, Bac, Trung)",
    version="2.0.0",
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
async def get_limits(region: str = Query(default='xsmn')):
    """Get current limit status for all 100 lô numbers (00-99) for a region."""
    region = _validate_region(region)
    try:
        summary = get_limit_summary(region=region)
        return {
            "status": "success",
            "region": region,
            "region_label": REGION_LABELS.get(region, region),
            "data": summary,
            "config": {
                "point_value": POINT_VALUE,
                "win_multiplier": WIN_MULTIPLIER,
                "min_limit": MIN_LIMIT,
                "base_schedule": BASE_LIMIT_SCHEDULE,
                "consecutive_limits": CONSECUTIVE_LIMITS,
                "price_per_point": PRICE_PER_POINT,
                "cost_multiplier": COST_MULTIPLIER.get(region, 18),
            },
            "updated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/limits/{lo_number}")
async def get_limit_detail(lo_number: str, region: str = Query(default='xsmn')):
    """Get detailed limit info for a specific lô number."""
    region = _validate_region(region)
    if not lo_number.isdigit() or len(lo_number) != 2:
        raise HTTPException(status_code=400, detail="Lô number must be 2 digits (00-99)")

    status = get_lo_status(lo_number, region=region)
    if not status:
        raise HTTPException(status_code=404, detail=f"Lô {lo_number} not found for region {region}")

    # Get recent history
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT date, count FROM lo_daily 
        WHERE lo_number = ? AND region = ?
        ORDER BY date DESC LIMIT 30
    ''', (lo_number, region))
    history = [dict(row) for row in cursor.fetchall()]

    # Get bet history
    cursor.execute('''
        SELECT date, bet_amount, is_win, profit 
        FROM bet_history 
        WHERE lo_number = ? AND region = ?
        ORDER BY date DESC LIMIT 30
    ''', (lo_number, region))
    bets = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return {
        "status": "success",
        "region": region,
        "data": {
            **status,
            "history": history,
            "bet_history": bets,
        }
    }


@app.get("/api/consecutive")
async def get_consecutive(region: str = Query(default='xsmn')):
    """Get list of lô numbers currently on consecutive streaks."""
    region = _validate_region(region)
    try:
        data = get_consecutive_los(region=region)
        return {"status": "success", "region": region, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# API ROUTES - RESULTS
# ═══════════════════════════════════════════════════════════

@app.get("/api/results/today")
async def get_today_results(region: str = Query(default='xsmn')):
    """Get today's lottery results."""
    region = _validate_region(region)
    today = datetime.now().strftime('%Y-%m-%d')
    results = get_results_for_date(today, region=region)

    if not results:
        # Try yesterday if today's not available
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        results = get_results_for_date(yesterday, region=region)
        if results:
            return {"status": "success", "date": yesterday, "region": region,
                    "data": results, "note": "Showing yesterday's results"}
        return {"status": "success", "date": today, "region": region,
                "data": [], "note": "No results available yet"}

    return {"status": "success", "date": today, "region": region, "data": results}


@app.get("/api/results/date/{date_str}")
async def get_results_by_date(date_str: str, region: str = Query(default=None)):
    """Get lottery results for a specific date."""
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    if region:
        region = _validate_region(region)
    results = get_results_for_date(date_str, region=region)
    return {"status": "success", "date": date_str, "region": region, "data": results}


@app.get("/api/results/history")
async def get_history(days: int = Query(default=30, ge=1, le=90),
                      region: str = Query(default='xsmn')):
    """Get lottery results history for the last N days."""
    region = _validate_region(region)
    history = get_results_history(days, region=region)

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

    return {"status": "success", "days": days, "region": region, "data": by_date}


@app.get("/api/results/lo-daily")
async def get_lo_daily_history(days: int = Query(default=30, ge=1, le=90),
                                region: str = Query(default='xsmn')):
    """Get daily lô appearance data for heat map / tracking."""
    region = _validate_region(region)
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT date, lo_number, count 
        FROM lo_daily 
        WHERE date >= ? AND region = ?
        ORDER BY date DESC, lo_number ASC
    ''', (cutoff, region))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {"status": "success", "region": region, "data": rows}


# ═══════════════════════════════════════════════════════════
# API ROUTES - STATISTICS / PROFIT
# ═══════════════════════════════════════════════════════════

@app.get("/api/stats/profit")
async def get_profit_stats(days: int = Query(default=30, ge=1, le=90),
                           region: str = Query(default='xsmn')):
    """Get profit/loss statistics for the last N days."""
    region = _validate_region(region)
    try:
        stats = calculate_period_profit(days, region=region)
        return {"status": "success", "data": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/profit/chart")
async def get_profit_chart(days: int = Query(default=30, ge=1, le=90),
                           region: str = Query(default='xsmn')):
    """Get profit chart data for Chart.js visualization."""
    region = _validate_region(region)
    try:
        chart_data = get_profit_chart_data(days, region=region)
        return {"status": "success", "data": chart_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/lo-breakdown")
async def get_lo_breakdown(days: int = Query(default=30, ge=1, le=90),
                           region: str = Query(default='xsmn')):
    """Get profit breakdown per lô number."""
    region = _validate_region(region)
    try:
        breakdown = get_lo_profit_breakdown(days, region=region)
        return {"status": "success", "data": breakdown}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# API ROUTES - PREDICTION (Promax statistical engine)
# ═══════════════════════════════════════════════════════════

@app.get("/api/predict")
async def get_predictions(
    region: str = Query(default='xsmn'),
    window: int = Query(default=60, ge=7, le=180),
):
    """Run the multi-model probability prediction for a region."""
    region = _validate_region(region)
    try:
        result = run_prediction(region=region, window_days=window)
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# API ROUTES - SCRAPING / DATA MANAGEMENT
# ═══════════════════════════════════════════════════════════

@app.post("/api/scrape/today")
async def trigger_scrape_today(background_tasks: BackgroundTasks,
                               region: str = Query(default='xsmn')):
    """Trigger scraping of today's results for a region."""
    region = _validate_region(region)
    background_tasks.add_task(_scrape_and_update_today, region)
    return {"status": "started", "region": region,
            "message": f"Scraping today's {region.upper()} results in background..."}


@app.post("/api/scrape/range")
async def trigger_scrape_range(
    days: int = Query(default=30, ge=1, le=90),
    region: str = Query(default='xsmn'),
    background_tasks: BackgroundTasks = None
):
    """Trigger scraping of the last N days for a specific region."""
    region = _validate_region(region)
    background_tasks.add_task(_scrape_and_update_range, days, region)
    return {
        "status": "started",
        "region": region,
        "message": f"Scraping last {days} days of {region.upper()} in background..."
    }


@app.post("/api/scrape/all")
async def trigger_scrape_all(
    days: int = Query(default=30, ge=1, le=90),
    background_tasks: BackgroundTasks = None
):
    """Trigger scraping of ALL 3 regions for the last N days."""
    background_tasks.add_task(_scrape_and_update_all, days)
    return {
        "status": "started",
        "message": f"Scraping all 3 regions ({days} days each) in background. This may take several minutes..."
    }


@app.post("/api/recalculate")
async def trigger_recalculate(background_tasks: BackgroundTasks,
                              region: str = Query(default=None)):
    """Recalculate all lô statuses from stored history."""
    if region:
        region = _validate_region(region)
    background_tasks.add_task(recalculate_all_from_history, region)
    msg = f"Recalculating limits for {region.upper()}" if region else "Recalculating all regions"
    return {"status": "started", "message": msg}


@app.get("/api/scrape/status")
async def get_scrape_status(region: str = Query(default=None)):
    """Get list of scraped dates, optionally filtered by region."""
    if region:
        region = _validate_region(region)
    dates = get_scraped_dates(region=region)
    
    # Group by region
    by_region = {}
    for entry in dates:
        rgn = entry['region']
        if rgn not in by_region:
            by_region[rgn] = []
        by_region[rgn].append(entry['date'])
    
    return {
        "status": "success",
        "by_region": {r: {"dates": d, "count": len(d), "latest": d[0] if d else None}
                      for r, d in by_region.items()},
        "total_records": len(dates),
    }


@app.post("/api/cleanup")
async def trigger_cleanup(days: int = Query(default=30)):
    """Clean up data older than N days."""
    deleted = cleanup_old_data(days)
    return {"status": "success", "deleted_records": deleted}


# ═══════════════════════════════════════════════════════════
# API ROUTES - METADATA
# ═══════════════════════════════════════════════════════════

@app.get("/api/regions")
async def get_regions():
    """Get list of available regions."""
    return {
        "status": "success",
        "regions": [
            {"id": r, "label": REGION_LABELS.get(r, r)}
            for r in VALID_REGIONS
        ]
    }


# ═══════════════════════════════════════════════════════════
# BACKGROUND TASKS
# ═══════════════════════════════════════════════════════════

def _scrape_and_update_today(region: str):
    """Background task: scrape today and update limits for a region."""
    try:
        result = scrape_today(region=region)
        if result:
            today = datetime.now().strftime('%Y-%m-%d')
            update_all_lo_status(today, region=region)
            print(f"[OK] Scraped and updated {region.upper()} for today ({today})")
        else:
            print(f"[WARN] No {region.upper()} results found for today")
    except Exception as e:
        print(f"[ERR] Error scraping {region.upper()} today: {e}")


def _scrape_and_update_range(days: int, region: str):
    """Background task: scrape range and recalculate limits for a region."""
    try:
        count = scrape_last_n_days(days, region=region, delay=1.5)
        if count > 0:
            recalculate_all_from_history(region=region)
            print(f"[OK] Scraped {count} days of {region.upper()} and recalculated limits")
        else:
            print(f"[WARN] No days were scraped for {region.upper()}")
    except Exception as e:
        print(f"[ERR] Error scraping {region.upper()} range: {e}")


def _scrape_and_update_all(days: int):
    """Background task: scrape ALL regions and recalculate."""
    try:
        counts = scrape_all_regions_range(days, delay=1.5)
        recalculate_all_from_history(region=None)  # Recalculate all
        total = sum(counts.values())
        print(f"[OK] Scraped {total} total days across all regions: {counts}")
    except Exception as e:
        print(f"[ERR] Error scraping all regions: {e}")


# ═══════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    import uvicorn
    print("=" * 60)
    print("   LOTTERY LIMIT MANAGEMENT SYSTEM - 3 MIEN")
    print("   Mien Nam | Mien Bac | Mien Trung")
    print("   http://localhost:8899")
    print("=" * 60)
    uvicorn.run("main:app", host="0.0.0.0", port=8899, reload=True)
