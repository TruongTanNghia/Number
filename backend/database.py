"""
Database module for XSMN Lottery Limit System.
Uses SQLite for persistent storage of lottery results, 
lô tracking status, and bet history.
"""

import sqlite3
import os
from datetime import datetime, timedelta

# Database path - stored in /data/ directory
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'lottery.db')


def get_connection():
    """Get a SQLite database connection."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize database tables and seed initial data."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript('''
        -- Raw lottery results from each province
        CREATE TABLE IF NOT EXISTS lottery_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            province TEXT NOT NULL,
            prize_type TEXT NOT NULL,
            number TEXT NOT NULL,
            lo_number TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Aggregated: which lô appeared each day (across all provinces)
        CREATE TABLE IF NOT EXISTS lo_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            lo_number TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            UNIQUE(date, lo_number)
        );

        -- Current tracking status for each of the 100 lô (00-99)
        CREATE TABLE IF NOT EXISTS lo_status (
            lo_number TEXT PRIMARY KEY,
            last_appeared_date TEXT,
            days_since_last INTEGER DEFAULT 0,
            consecutive_days INTEGER DEFAULT 0,
            current_limit INTEGER DEFAULT 200,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Simulated bet history for P&L tracking
        CREATE TABLE IF NOT EXISTS bet_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            lo_number TEXT NOT NULL,
            bet_amount INTEGER NOT NULL,
            is_win INTEGER NOT NULL DEFAULT 0,
            profit INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Track which dates have been scraped
        CREATE TABLE IF NOT EXISTS scraped_dates (
            date TEXT PRIMARY KEY,
            province_count INTEGER DEFAULT 0,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_results_date ON lottery_results(date);
        CREATE INDEX IF NOT EXISTS idx_results_lo ON lottery_results(lo_number);
        CREATE INDEX IF NOT EXISTS idx_lo_daily_date ON lo_daily(date);
        CREATE INDEX IF NOT EXISTS idx_lo_daily_lo ON lo_daily(lo_number);
        CREATE INDEX IF NOT EXISTS idx_bet_date ON bet_history(date);
    ''')

    # Initialize 100 lô numbers (00-99) if not exists
    for i in range(100):
        lo = f'{i:02d}'
        cursor.execute('''
            INSERT OR IGNORE INTO lo_status (lo_number, days_since_last, consecutive_days, current_limit)
            VALUES (?, 0, 0, 200)
        ''', (lo,))

    conn.commit()
    conn.close()
    print(f"[DB] Database initialized at {DB_PATH}")


def save_lottery_results(date_str: str, province: str, results: list):
    """
    Save lottery results for a specific date and province.
    
    Args:
        date_str: Date string in format 'YYYY-MM-DD'
        province: Province name (e.g., 'TP HCM')
        results: List of dicts with 'prize_type' and 'number' keys
    """
    conn = get_connection()
    cursor = conn.cursor()

    for result in results:
        number = result['number'].strip()
        lo_number = number[-2:]  # Last 2 digits = lô tô

        cursor.execute('''
            INSERT INTO lottery_results (date, province, prize_type, number, lo_number)
            VALUES (?, ?, ?, ?, ?)
        ''', (date_str, province, result['prize_type'], number, lo_number))

        # Update aggregated lo_daily
        cursor.execute('''
            INSERT INTO lo_daily (date, lo_number, count)
            VALUES (?, ?, 1)
            ON CONFLICT(date, lo_number) DO UPDATE SET count = count + 1
        ''', (date_str, lo_number))

    # Mark date as scraped
    cursor.execute('''
        INSERT INTO scraped_dates (date, province_count)
        VALUES (?, 1)
        ON CONFLICT(date) DO UPDATE SET province_count = province_count + 1
    ''', (date_str,))

    conn.commit()
    conn.close()


def is_date_scraped(date_str: str) -> bool:
    """Check if a date has already been scraped."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM scraped_dates WHERE date = ?', (date_str,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def get_lo_appeared_on_date(date_str: str) -> set:
    """Get the set of lô numbers that appeared on a specific date."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT lo_number FROM lo_daily WHERE date = ?', (date_str,))
    rows = cursor.fetchall()
    conn.close()
    return {row['lo_number'] for row in rows}


def get_lo_daily_count(date_str: str, lo_number: str) -> int:
    """Get how many times a lô appeared on a given date."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT count FROM lo_daily WHERE date = ? AND lo_number = ?',
        (date_str, lo_number)
    )
    row = cursor.fetchone()
    conn.close()
    return row['count'] if row else 0


def get_all_lo_status():
    """Get current status of all 100 lô numbers."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM lo_status ORDER BY lo_number')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_lo_status(lo_number: str):
    """Get current status of a specific lô number."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM lo_status WHERE lo_number = ?', (lo_number,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_lo_status(lo_number: str, last_appeared_date: str,
                     days_since_last: int, consecutive_days: int,
                     current_limit: int):
    """Update the tracking status for a specific lô number."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE lo_status 
        SET last_appeared_date = ?,
            days_since_last = ?,
            consecutive_days = ?,
            current_limit = ?,
            updated_at = ?
        WHERE lo_number = ?
    ''', (last_appeared_date, days_since_last, consecutive_days,
          current_limit, datetime.now().isoformat(), lo_number))
    conn.commit()
    conn.close()


def save_bet_record(date_str: str, lo_number: str, bet_amount: int,
                    is_win: bool, profit: int):
    """Save a bet record for P&L tracking."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO bet_history (date, lo_number, bet_amount, is_win, profit)
        VALUES (?, ?, ?, ?, ?)
    ''', (date_str, lo_number, bet_amount, 1 if is_win else 0, profit))
    conn.commit()
    conn.close()


def get_bet_history(days: int = 30):
    """Get bet history for the last N days."""
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT * FROM bet_history 
        WHERE date >= ? 
        ORDER BY date DESC, lo_number ASC
    ''', (cutoff,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_results_for_date(date_str: str):
    """Get all lottery results for a specific date."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM lottery_results 
        WHERE date = ? 
        ORDER BY province, prize_type
    ''', (date_str,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_results_history(days: int = 30):
    """Get lottery results for the last N days."""
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT date, lo_number, SUM(count) as total_count 
        FROM lo_daily 
        WHERE date >= ?
        GROUP BY date, lo_number
        ORDER BY date DESC
    ''', (cutoff,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_scraped_dates():
    """Get list of all scraped dates."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT date FROM scraped_dates ORDER BY date DESC')
    rows = cursor.fetchall()
    conn.close()
    return [row['date'] for row in rows]


def cleanup_old_data(days: int = 30):
    """Remove data older than N days to keep DB size manageable."""
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    cursor.execute('DELETE FROM lottery_results WHERE date < ?', (cutoff,))
    cursor.execute('DELETE FROM lo_daily WHERE date < ?', (cutoff,))
    cursor.execute('DELETE FROM bet_history WHERE date < ?', (cutoff,))
    cursor.execute('DELETE FROM scraped_dates WHERE date < ?', (cutoff,))

    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted
