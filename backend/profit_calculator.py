"""
Profit & Loss Calculator for Lottery Bet System.
Supports multiple regions (XSMN, XSMB, XSMT).

Pricing model (per region):
- Xác cược (chi phí 1 điểm 1 con) = COST_MULTIPLIER[region] × PRICE_PER_POINT
  - MN/MT: 18 × 75 = 1.350đ
  - MB:    27 × 75 = 2.025đ
- Trúng cược (tiền ăn 1 điểm/1 lần) = PRICE_PER_POINT = 75đ
  → Win amount mỗi ngày = điểm × 75 × số lần lô về trong ngày.
"""

from datetime import datetime, timedelta
from database import get_connection, get_lo_appeared_on_date, get_all_lo_status
from limit_engine import (
    PRICE_PER_POINT, COST_MULTIPLIER,
    get_bet_cost, get_win_amount,
)


# ═══════════════════════════════════════════════════════════
# DAILY PROFIT — recompute on the fly from limits + lo_daily
# (does NOT depend on bet_history table; bet_history kept for legacy)
# ═══════════════════════════════════════════════════════════

def calculate_daily_profit(date_str: str, region: str = 'xsmn') -> dict:
    """
    Calculate cost / win / net profit for a date assuming we bet
    `current_limit` points on every lô (00–99) for that region.

    For each lô:
      - cost = limit × COST_MULTIPLIER[region] × 75
      - if appeared `n` times that day → win = limit × 75 × n
      - profit_per_lo = win - cost
    """
    cost_mult = COST_MULTIPLIER.get(region, 18)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT lo_number, current_limit FROM lo_status WHERE region = ?',
        (region,)
    )
    limits = {row['lo_number']: row['current_limit'] for row in cursor.fetchall()}

    cursor.execute(
        'SELECT lo_number, count FROM lo_daily WHERE date = ? AND region = ?',
        (date_str, region)
    )
    appearances = {row['lo_number']: row['count'] for row in cursor.fetchall()}
    conn.close()

    if not limits:
        return _empty_daily(date_str)

    total_cost = 0
    total_win = 0
    win_count = 0
    lose_count = 0

    for lo, limit in limits.items():
        cost = limit * cost_mult * PRICE_PER_POINT
        total_cost += cost

        n = appearances.get(lo, 0)
        if n > 0:
            win = limit * PRICE_PER_POINT * n
            total_win += win
            win_count += 1
        else:
            lose_count += 1

    net = total_win - total_cost

    return {
        'date': date_str,
        'region': region,
        'total_bet_vnd': total_cost,
        'total_win_vnd': total_win,
        'total_loss_vnd': total_cost - total_win if total_cost > total_win else 0,
        'net_profit_vnd': net,
        'win_count': win_count,
        'lose_count': lose_count,
        'total_bets': win_count + lose_count,
        'win_rate': (win_count / 100 * 100) if (win_count + lose_count) > 0 else 0,
    }


def _empty_daily(date_str: str) -> dict:
    return {
        'date': date_str,
        'total_bet_vnd': 0,
        'total_win_vnd': 0,
        'total_loss_vnd': 0,
        'net_profit_vnd': 0,
        'win_count': 0,
        'lose_count': 0,
        'total_bets': 0,
        'win_rate': 0,
    }


def calculate_period_profit(days: int = 30, region: str = 'xsmn') -> dict:
    """
    Aggregate profit/loss over the last N days for a region.
    Skip days that have no data (no lô_daily entries).
    """
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    cursor.execute(
        'SELECT DISTINCT date FROM lo_daily WHERE region = ? AND date >= ? ORDER BY date DESC',
        (region, cutoff)
    )
    dates = [row['date'] for row in cursor.fetchall()]
    conn.close()

    daily_results = []
    total_cost = 0
    total_win = 0
    total_wins = 0
    total_losses = 0

    for date_str in dates:
        daily = calculate_daily_profit(date_str, region=region)
        daily_results.append(daily)
        total_cost += daily['total_bet_vnd']
        total_win += daily['total_win_vnd']
        total_wins += daily['win_count']
        total_losses += daily['lose_count']

    net = total_win - total_cost
    total_bets = total_wins + total_losses

    return {
        'period_days': days,
        'region': region,
        'total_bet_vnd': total_cost,
        'total_win_vnd': total_win,
        'total_loss_vnd': total_cost - total_win if total_cost > total_win else 0,
        'net_profit_vnd': net,
        'total_bets': total_bets,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'win_rate': (total_wins / total_bets * 100) if total_bets > 0 else 0,
        'roi': (net / total_cost * 100) if total_cost > 0 else 0,
        'daily_breakdown': daily_results,
    }


# ═══════════════════════════════════════════════════════════
# CHART DATA
# ═══════════════════════════════════════════════════════════

def get_profit_chart_data(days: int = 30, region: str = 'xsmn') -> dict:
    """Format chart data for Chart.js (last N days, oldest first)."""
    labels = []
    win_data = []
    loss_data = []
    net_data = []
    cumulative = 0
    cumulative_data = []

    for i in range(days - 1, -1, -1):
        date = datetime.now() - timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        display_date = date.strftime('%d/%m')

        daily = calculate_daily_profit(date_str, region=region)
        labels.append(display_date)
        win_data.append(daily['total_win_vnd'])
        loss_data.append(-daily['total_bet_vnd'])  # bet shown as negative
        net_data.append(daily['net_profit_vnd'])
        cumulative += daily['net_profit_vnd']
        cumulative_data.append(cumulative)

    return {
        'labels': labels,
        'datasets': {
            'wins': win_data,
            'losses': loss_data,
            'net': net_data,
            'cumulative': cumulative_data,
        }
    }


# ═══════════════════════════════════════════════════════════
# PER-LÔ BREAKDOWN
# ═══════════════════════════════════════════════════════════

def get_lo_profit_breakdown(days: int = 30, region: str = 'xsmn') -> list:
    """
    Per-lô profit breakdown over the last N days.
    Uses CURRENT limit as the simulated bet for every day in the window.
    """
    cost_mult = COST_MULTIPLIER.get(region, 18)
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT lo_number, current_limit FROM lo_status WHERE region = ? ORDER BY lo_number',
        (region,)
    )
    limits = [(row['lo_number'], row['current_limit']) for row in cursor.fetchall()]

    cursor.execute('''
        SELECT lo_number, COUNT(*) as appear_days, SUM(count) as total_count
        FROM lo_daily
        WHERE region = ? AND date >= ?
        GROUP BY lo_number
    ''', (region, cutoff))
    appearances = {row['lo_number']: dict(row) for row in cursor.fetchall()}

    cursor.execute(
        'SELECT COUNT(DISTINCT date) as n FROM lo_daily WHERE region = ? AND date >= ?',
        (region, cutoff)
    )
    total_days = cursor.fetchone()['n'] or 0
    conn.close()

    results = []
    for lo, limit in limits:
        appear = appearances.get(lo, {})
        appear_days = appear.get('appear_days', 0) or 0
        total_count = appear.get('total_count', 0) or 0

        cost = limit * cost_mult * PRICE_PER_POINT * total_days
        win = limit * PRICE_PER_POINT * total_count
        net = win - cost

        results.append({
            'lo_number': lo,
            'limit_points': limit,
            'appear_days': appear_days,
            'total_appearances': total_count,
            'total_bet': cost,
            'total_win': win,
            'net_profit': net,
        })

    results.sort(key=lambda r: r['net_profit'], reverse=True)
    return results


# ═══════════════════════════════════════════════════════════
# LEGACY: simulate_bets_for_date (kept for compatibility)
# ═══════════════════════════════════════════════════════════

def simulate_bets_for_date(date_str: str, bet_strategy: str = 'max_limit', region: str = 'xsmn'):
    """No-op: profit now derived directly from lo_status + lo_daily."""
    print(f"[ProfitCalc/{region.upper()}] simulate_bets_for_date is deprecated (auto-derived now)")


def format_vnd(amount: int) -> str:
    if amount >= 0:
        return f"+{amount:,.0f}đ"
    return f"{amount:,.0f}đ"
