"""
Limit Engine for XSMN Lottery Bet Management.

Implements the dynamic bet limit system:
1. Base limit decreases by 20 points for each day since the lô last appeared
2. Consecutive hit penalties reduce the limit further
3. After 4 consecutive hits, the limit resets
"""

from datetime import datetime, timedelta
from database import (
    get_all_lo_status, get_lo_appeared_on_date, update_lo_status,
    get_connection, get_lo_status
)

# ═══════════════════════════════════════════════════════════
# CONFIGURATION - Adjustable parameters
# ═══════════════════════════════════════════════════════════

# Base limit schedule: days_since_last_appeared -> max_limit
BASE_LIMIT_SCHEDULE = {
    0: 200,   # Lô vừa về hôm nay (hoặc ngày 1)
    1: 200,   # Ngày 1 kể từ lô về
    2: 180,   # Ngày 2
    3: 160,   # Ngày 3
    4: 140,   # Ngày 4
    5: 120,   # Ngày 5
    6: 100,   # Ngày 6
    7: 80,    # Ngày 7
    8: 60,    # Ngày 8
    9: 40,    # Ngày 9
    10: 20,   # Ngày 10
}
MIN_LIMIT = 10  # Ngày 11 trở đi

# Consecutive hit penalties
CONSECUTIVE_LIMITS = {
    2: 150,   # Lô về 2 ngày liên tiếp → max 150đ
    3: 100,   # Lô về 3 ngày liên tiếp → max 100đ
    4: 50,    # Lô về 4 ngày liên tiếp → max 50đ
}
CONSECUTIVE_RESET_AFTER = 4  # Qua 4 ngày → reset

# Betting parameters
POINT_VALUE = 23000      # 1 điểm = 23,000 VND
WIN_MULTIPLIER = 80      # Ăn 1 trả 80 (lô 2 số XSMN)


def calculate_base_limit(days_since_last: int) -> int:
    """
    Calculate the base limit based on days since the lô last appeared.
    
    Args:
        days_since_last: Number of days since the lô last appeared
        
    Returns:
        int: Maximum bet limit in points (điểm)
    """
    if days_since_last in BASE_LIMIT_SCHEDULE:
        return BASE_LIMIT_SCHEDULE[days_since_last]
    return MIN_LIMIT


def calculate_consecutive_limit(consecutive_days: int) -> int:
    """
    Calculate the consecutive hit limit.
    
    Args:
        consecutive_days: Number of consecutive days the lô has appeared
        
    Returns:
        int: Maximum bet limit due to consecutive hits, or None if no penalty
    """
    if consecutive_days > CONSECUTIVE_RESET_AFTER:
        # Reset after 4 consecutive days
        return None  # No penalty - reset
    
    if consecutive_days in CONSECUTIVE_LIMITS:
        return CONSECUTIVE_LIMITS[consecutive_days]
    
    return None  # No consecutive penalty


def calculate_effective_limit(days_since_last: int, consecutive_days: int) -> int:
    """
    Calculate the effective (final) limit considering both base and consecutive rules.
    
    The effective limit is the MINIMUM of:
    - Base limit (based on days since last appearance)
    - Consecutive penalty (if applicable)
    
    Args:
        days_since_last: Days since the lô last appeared
        consecutive_days: Number of consecutive days it appeared
        
    Returns:
        int: Final effective maximum bet limit
    """
    base_limit = calculate_base_limit(days_since_last)
    
    consec_limit = calculate_consecutive_limit(consecutive_days)
    
    if consec_limit is not None:
        return min(base_limit, consec_limit)
    
    return base_limit


def update_all_lo_status(target_date: str = None):
    """
    Update the status and limits for all 100 lô numbers based on results.
    
    This should be called after new results are scraped.
    Processes dates sequentially to maintain correct consecutive tracking.
    
    Args:
        target_date: Date string (YYYY-MM-DD) to process. If None, uses today.
    """
    if target_date is None:
        target_date = datetime.now().strftime('%Y-%m-%d')

    # Get all lô that appeared on this date
    appeared_today = get_lo_appeared_on_date(target_date)
    
    print(f"[LimitEngine] Updating for {target_date}: {len(appeared_today)} lô appeared")

    # Update each of the 100 lô
    for i in range(100):
        lo = f'{i:02d}'
        current = get_lo_status(lo)
        
        if current is None:
            # Initialize
            days_since = 0
            consec = 0
            last_date = None
        else:
            days_since = current['days_since_last']
            consec = current['consecutive_days']
            last_date = current['last_appeared_date']

        if lo in appeared_today:
            # Lô appeared today
            if last_date == _get_previous_date(target_date):
                # Appeared yesterday too - consecutive!
                consec += 1
            else:
                # First appearance or gap - reset consecutive
                consec = 1
            
            # Check if we need to reset after 4 consecutive
            if consec > CONSECUTIVE_RESET_AFTER:
                consec = 1  # Reset consecutive counter
            
            days_since = 0
            last_date = target_date
        else:
            # Lô did NOT appear today
            days_since += 1
            # Don't reset consecutive here - it reflects the LAST streak
            # Only reset when it appears again after a gap (handled above)

        # Calculate new limit
        new_limit = calculate_effective_limit(days_since, consec)

        # Save updated status
        update_lo_status(lo, last_date, days_since, consec, new_limit)

    print(f"[LimitEngine] All 100 lô updated for {target_date}")


def recalculate_all_from_history():
    """
    Recalculate all lô statuses from scratch using the stored daily history.
    Useful for rebuilding after data changes or initial setup.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get all dates with data, in chronological order
    cursor.execute('SELECT DISTINCT date FROM lo_daily ORDER BY date ASC')
    dates = [row['date'] for row in cursor.fetchall()]
    conn.close()
    
    if not dates:
        print("[LimitEngine] No historical data to recalculate from")
        return
    
    # Reset all lô statuses
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE lo_status 
        SET last_appeared_date = NULL, 
            days_since_last = 0, 
            consecutive_days = 0, 
            current_limit = 200
    ''')
    conn.commit()
    conn.close()
    
    # Process each date chronologically
    for date_str in dates:
        update_all_lo_status(date_str)
    
    print(f"[LimitEngine] Recalculated from {len(dates)} days of history")


def get_limit_summary():
    """
    Get a summary of all 100 lô with their current limits and status.
    
    Returns:
        list of dicts with limit info for each lô
    """
    all_status = get_all_lo_status()
    summary = []
    
    for status in all_status:
        lo = status['lo_number']
        days = status['days_since_last']
        consec = status['consecutive_days']
        limit = status['current_limit']
        last_date = status['last_appeared_date']
        
        # Determine status category
        if consec >= 4:
            category = 'hot_streak'
        elif consec >= 2:
            category = 'consecutive'
        elif days == 0:
            category = 'just_hit'
        elif days <= 3:
            category = 'recent'
        elif days <= 7:
            category = 'cooling'
        else:
            category = 'cold'
        
        summary.append({
            'lo_number': lo,
            'days_since_last': days,
            'consecutive_days': consec,
            'current_limit': limit,
            'last_appeared_date': last_date,
            'category': category,
            'base_limit': calculate_base_limit(days),
            'consecutive_penalty': calculate_consecutive_limit(consec),
        })
    
    return summary


def get_consecutive_los():
    """Get list of lô numbers currently on consecutive streaks."""
    all_status = get_all_lo_status()
    consecutive = []
    
    for status in all_status:
        if status['consecutive_days'] >= 2:
            consecutive.append({
                'lo_number': status['lo_number'],
                'consecutive_days': status['consecutive_days'],
                'current_limit': status['current_limit'],
                'last_appeared_date': status['last_appeared_date'],
            })
    
    # Sort by consecutive days descending
    consecutive.sort(key=lambda x: x['consecutive_days'], reverse=True)
    return consecutive


def _get_previous_date(date_str: str) -> str:
    """Get the previous date string."""
    date = datetime.strptime(date_str, '%Y-%m-%d')
    prev = date - timedelta(days=1)
    return prev.strftime('%Y-%m-%d')


if __name__ == '__main__':
    # Test limit calculations
    print("=== Base Limit Schedule ===")
    for days in range(15):
        print(f"  Day {days}: {calculate_base_limit(days)}đ")
    
    print("\n=== Consecutive Penalty ===")
    for consec in range(1, 6):
        limit = calculate_consecutive_limit(consec)
        print(f"  {consec} consecutive: {limit if limit else 'No penalty (reset)'}đ")
    
    print("\n=== Effective Limit Examples ===")
    print(f"  Day 0, consec 0: {calculate_effective_limit(0, 0)}đ")
    print(f"  Day 0, consec 2: {calculate_effective_limit(0, 2)}đ")
    print(f"  Day 0, consec 3: {calculate_effective_limit(0, 3)}đ")
    print(f"  Day 0, consec 4: {calculate_effective_limit(0, 4)}đ")
    print(f"  Day 0, consec 5: {calculate_effective_limit(0, 5)}đ (reset)")
    print(f"  Day 5, consec 0: {calculate_effective_limit(5, 0)}đ")
    print(f"  Day 10, consec 0: {calculate_effective_limit(10, 0)}đ")
    print(f"  Day 15, consec 0: {calculate_effective_limit(15, 0)}đ")
