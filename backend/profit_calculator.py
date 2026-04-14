"""
Profit & Loss Calculator for XSMN Lottery Bet System.

Calculates total revenue and costs based on bet history,
simulating P&L over the last 30 days.
"""

from datetime import datetime, timedelta
from database import (
    get_bet_history, save_bet_record, get_connection,
    get_lo_appeared_on_date, get_all_lo_status
)
from limit_engine import POINT_VALUE, WIN_MULTIPLIER


def calculate_daily_profit(date_str: str) -> dict:
    """
    Calculate profit/loss for a specific date.
    
    For each lô number that was bet on:
    - If it appeared: WIN = bet_amount × WIN_MULTIPLIER × POINT_VALUE
    - If it didn't appear: LOSS = -bet_amount × POINT_VALUE
    
    Returns:
        dict with daily P&L breakdown
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT lo_number, bet_amount, is_win, profit
        FROM bet_history 
        WHERE date = ?
    ''', (date_str,))
    bets = cursor.fetchall()
    conn.close()
    
    total_bet = 0
    total_win = 0
    total_loss = 0
    win_count = 0
    lose_count = 0
    details = []
    
    for bet in bets:
        bet_dict = dict(bet)
        total_bet += bet_dict['bet_amount']
        
        if bet_dict['is_win']:
            total_win += bet_dict['profit']
            win_count += 1
        else:
            total_loss += abs(bet_dict['profit'])
            lose_count += 1
        
        details.append(bet_dict)
    
    net_profit = total_win - total_loss
    
    return {
        'date': date_str,
        'total_bet_points': total_bet,
        'total_bet_vnd': total_bet * POINT_VALUE,
        'total_win_vnd': total_win,
        'total_loss_vnd': total_loss,
        'net_profit_vnd': net_profit,
        'win_count': win_count,
        'lose_count': lose_count,
        'total_bets': win_count + lose_count,
        'win_rate': (win_count / (win_count + lose_count) * 100) if (win_count + lose_count) > 0 else 0,
        'details': details,
    }


def calculate_period_profit(days: int = 30) -> dict:
    """
    Calculate total P&L for the last N days.
    
    Returns:
        dict with period P&L summary and daily breakdown
    """
    daily_results = []
    total_win = 0
    total_loss = 0
    total_bets = 0
    total_wins = 0
    total_losses = 0
    
    for i in range(days):
        date = datetime.now() - timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        daily = calculate_daily_profit(date_str)
        
        if daily['total_bets'] > 0:
            daily_results.append(daily)
            total_win += daily['total_win_vnd']
            total_loss += daily['total_loss_vnd']
            total_bets += daily['total_bets']
            total_wins += daily['win_count']
            total_losses += daily['lose_count']
    
    net = total_win - total_loss
    
    return {
        'period_days': days,
        'total_win_vnd': total_win,
        'total_loss_vnd': total_loss,
        'net_profit_vnd': net,
        'total_bets': total_bets,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'win_rate': (total_wins / total_bets * 100) if total_bets > 0 else 0,
        'roi': (net / (total_loss if total_loss > 0 else 1)) * 100,
        'daily_breakdown': sorted(daily_results, key=lambda x: x['date'], reverse=True),
    }


def simulate_bets_for_date(date_str: str, bet_strategy: str = 'max_limit'):
    """
    Simulate betting on all 100 lô for a given date using current limits.
    
    Strategy:
    - 'max_limit': Bet the current limit for each lô
    - 'fixed': Bet a fixed amount (e.g., 10đ) for each lô  
    - 'selective': Only bet on lô with limit >= threshold
    
    Args:
        date_str: Date to simulate bets for
        bet_strategy: Strategy to use
    """
    appeared = get_lo_appeared_on_date(date_str)
    all_status = get_all_lo_status()
    
    if not appeared:
        print(f"[ProfitCalc] No results for {date_str}, skipping simulation")
        return
    
    for status in all_status:
        lo = status['lo_number']
        limit = status['current_limit']
        
        if bet_strategy == 'max_limit':
            bet_amount = limit
        elif bet_strategy == 'fixed':
            bet_amount = 10
        elif bet_strategy == 'selective':
            if limit < 50:
                continue
            bet_amount = limit
        else:
            bet_amount = limit
        
        is_win = lo in appeared
        
        if is_win:
            # Win: bet_amount × WIN_MULTIPLIER × POINT_VALUE
            profit = bet_amount * WIN_MULTIPLIER * POINT_VALUE
        else:
            # Lose: -bet_amount × POINT_VALUE
            profit = -(bet_amount * POINT_VALUE)
        
        save_bet_record(date_str, lo, bet_amount, is_win, profit)
    
    print(f"[ProfitCalc] Simulated bets for {date_str}: "
          f"{len(appeared)} lô appeared out of 100")


def get_lo_profit_breakdown(days: int = 30) -> list:
    """
    Get profit breakdown per lô number.
    
    Returns:
        list of dicts with per-lô P&L summary
    """
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT 
            lo_number,
            SUM(bet_amount) as total_bet,
            SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN is_win = 0 THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN is_win = 1 THEN profit ELSE 0 END) as total_win,
            SUM(CASE WHEN is_win = 0 THEN ABS(profit) ELSE 0 END) as total_loss,
            SUM(profit) as net_profit
        FROM bet_history
        WHERE date >= ?
        GROUP BY lo_number
        ORDER BY net_profit DESC
    ''', (cutoff,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_profit_chart_data(days: int = 30) -> dict:
    """
    Get data formatted for chart visualization.
    
    Returns:
        dict with labels and datasets for Chart.js
    """
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
        
        daily = calculate_daily_profit(date_str)
        
        labels.append(display_date)
        win_data.append(daily['total_win_vnd'])
        loss_data.append(-daily['total_loss_vnd'])
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


def format_vnd(amount: int) -> str:
    """Format amount as VND currency string."""
    if amount >= 0:
        return f"+{amount:,.0f}đ"
    return f"{amount:,.0f}đ"
