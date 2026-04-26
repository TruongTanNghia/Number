"""
Database module for XSMN/XSMB Lottery Limit System.
Uses SQLite for persistent storage of lottery results, 
lô tracking status, and bet history.
Supports multiple regions (xsmn, xsmb).
"""

import sqlite3
import os
from datetime import datetime, timedelta

# Database path - stored in /data/ directory
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'lottery.db')

# Valid regions
VALID_REGIONS = ('xsmn', 'xsmb', 'xsmt')


def get_connection():
    """Get a SQLite database connection."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate_add_region(conn):
    """
    Migrate existing tables to add 'region' column.
    Called by init_db() if old schema detected.
    """
    cursor = conn.cursor()

    # Check if region column exists in lo_status
    cursor.execute("PRAGMA table_info(lo_status)")
    columns = [col[1] for col in cursor.fetchall()]

    if 'region' in columns:
        return  # Already migrated

    print("[DB] Migrating database to add region support...")

    # --- Migrate lottery_results ---
    try:
        cursor.execute("ALTER TABLE lottery_results ADD COLUMN region TEXT DEFAULT 'xsmn'")
    except sqlite3.OperationalError:
        pass  # Column might already exist

    # --- Migrate lo_daily ---
    try:
        cursor.execute("ALTER TABLE lo_daily ADD COLUMN region TEXT DEFAULT 'xsmn'")
        # Recreate unique constraint: need to rebuild table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lo_daily_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                lo_number TEXT NOT NULL,
                count INTEGER DEFAULT 1,
                region TEXT NOT NULL DEFAULT 'xsmn',
                UNIQUE(date, lo_number, region)
            )
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO lo_daily_new (date, lo_number, count, region)
            SELECT date, lo_number, count, COALESCE(region, 'xsmn') FROM lo_daily
        ''')
        cursor.execute('DROP TABLE lo_daily')
        cursor.execute('ALTER TABLE lo_daily_new RENAME TO lo_daily')
    except sqlite3.OperationalError:
        pass

    # --- Migrate lo_status: need composite PK (lo_number, region) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lo_status_new (
            lo_number TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT 'xsmn',
            last_appeared_date TEXT,
            days_since_last INTEGER DEFAULT 0,
            consecutive_days INTEGER DEFAULT 0,
            current_limit INTEGER DEFAULT 200,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (lo_number, region)
        )
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO lo_status_new (lo_number, region, last_appeared_date, days_since_last, consecutive_days, current_limit, updated_at)
        SELECT lo_number, 'xsmn', last_appeared_date, days_since_last, consecutive_days, current_limit, updated_at FROM lo_status
    ''')
    cursor.execute('DROP TABLE lo_status')
    cursor.execute('ALTER TABLE lo_status_new RENAME TO lo_status')

    # --- Migrate bet_history ---
    try:
        cursor.execute("ALTER TABLE bet_history ADD COLUMN region TEXT DEFAULT 'xsmn'")
    except sqlite3.OperationalError:
        pass

    # --- Migrate scraped_dates: need composite PK (date, region) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scraped_dates_new (
            date TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT 'xsmn',
            province_count INTEGER DEFAULT 0,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (date, region)
        )
    ''')
    cursor.execute('''
        INSERT OR IGNORE INTO scraped_dates_new (date, region, province_count, scraped_at)
        SELECT date, 'xsmn', province_count, scraped_at FROM scraped_dates
    ''')
    cursor.execute('DROP TABLE scraped_dates')
    cursor.execute('ALTER TABLE scraped_dates_new RENAME TO scraped_dates')

    conn.commit()
    print("[DB] Migration complete - region support added")


def init_db():
    """Initialize database tables and seed initial data."""
    conn = get_connection()
    cursor = conn.cursor()

    # Check if tables exist at all
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lo_status'")
    table_exists = cursor.fetchone() is not None

    if table_exists:
        # Try migration for existing databases
        _migrate_add_region(conn)
    
    # Create tables (for fresh installs)
    cursor.executescript('''
        -- Raw lottery results from each province
        CREATE TABLE IF NOT EXISTS lottery_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            province TEXT NOT NULL,
            prize_type TEXT NOT NULL,
            number TEXT NOT NULL,
            lo_number TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT 'xsmn',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Aggregated: which lô appeared each day (across all provinces in a region)
        CREATE TABLE IF NOT EXISTS lo_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            lo_number TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            region TEXT NOT NULL DEFAULT 'xsmn',
            UNIQUE(date, lo_number, region)
        );

        -- Current tracking status for each of the 100 lô (00-99) per region
        CREATE TABLE IF NOT EXISTS lo_status (
            lo_number TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT 'xsmn',
            last_appeared_date TEXT,
            days_since_last INTEGER DEFAULT 0,
            consecutive_days INTEGER DEFAULT 0,
            current_limit INTEGER DEFAULT 200,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (lo_number, region)
        );

        -- Simulated bet history for P&L tracking
        CREATE TABLE IF NOT EXISTS bet_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            lo_number TEXT NOT NULL,
            bet_amount INTEGER NOT NULL,
            is_win INTEGER NOT NULL DEFAULT 0,
            profit INTEGER NOT NULL DEFAULT 0,
            region TEXT NOT NULL DEFAULT 'xsmn',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Track which dates have been scraped per region
        CREATE TABLE IF NOT EXISTS scraped_dates (
            date TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT 'xsmn',
            province_count INTEGER DEFAULT 0,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (date, region)
        );

        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_results_date ON lottery_results(date);
        CREATE INDEX IF NOT EXISTS idx_results_lo ON lottery_results(lo_number);
        CREATE INDEX IF NOT EXISTS idx_results_region ON lottery_results(region);
        CREATE INDEX IF NOT EXISTS idx_lo_daily_date ON lo_daily(date);
        CREATE INDEX IF NOT EXISTS idx_lo_daily_lo ON lo_daily(lo_number);
        CREATE INDEX IF NOT EXISTS idx_lo_daily_region ON lo_daily(region);
        CREATE INDEX IF NOT EXISTS idx_bet_date ON bet_history(date);
        CREATE INDEX IF NOT EXISTS idx_bet_region ON bet_history(region);
    ''')

    # Initialize 100 lô numbers (00-99) for EACH region
    for region in VALID_REGIONS:
        for i in range(100):
            lo = f'{i:02d}'
            cursor.execute('''
                INSERT OR IGNORE INTO lo_status (lo_number, region, days_since_last, consecutive_days, current_limit)
                VALUES (?, ?, 0, 0, 200)
            ''', (lo, region))

    conn.commit()
    conn.close()
    print(f"[DB] Database initialized at {DB_PATH}")


def save_lottery_results(date_str: str, province: str, results: list, region: str = 'xsmn'):
    """
    Save lottery results for a specific date and province.
    
    Args:
        date_str: Date string in format 'YYYY-MM-DD'
        province: Province name (e.g., 'TP HCM', 'Miền Bắc')
        results: List of dicts with 'prize_type' and 'number' keys
        region: Region identifier ('xsmn' or 'xsmb')
    """
    conn = get_connection()
    cursor = conn.cursor()

    for result in results:
        number = result['number'].strip()
        lo_number = number[-2:]  # Last 2 digits = lô tô

        cursor.execute('''
            INSERT INTO lottery_results (date, province, prize_type, number, lo_number, region)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (date_str, province, result['prize_type'], number, lo_number, region))

        # Update aggregated lo_daily
        cursor.execute('''
            INSERT INTO lo_daily (date, lo_number, count, region)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(date, lo_number, region) DO UPDATE SET count = count + 1
        ''', (date_str, lo_number, region))

    # Mark date as scraped for this region
    cursor.execute('''
        INSERT INTO scraped_dates (date, region, province_count)
        VALUES (?, ?, 1)
        ON CONFLICT(date, region) DO UPDATE SET province_count = province_count + 1
    ''', (date_str, region))

    conn.commit()
    conn.close()


def is_date_scraped(date_str: str, region: str = 'xsmn') -> bool:
    """Check if a date has already been scraped for a given region."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM scraped_dates WHERE date = ? AND region = ?', (date_str, region))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def get_lo_appeared_on_date(date_str: str, region: str = 'xsmn') -> set:
    """Get the set of lô numbers that appeared on a specific date for a region."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT lo_number FROM lo_daily WHERE date = ? AND region = ?', (date_str, region))
    rows = cursor.fetchall()
    conn.close()
    return {row['lo_number'] for row in rows}


def get_lo_daily_count(date_str: str, lo_number: str, region: str = 'xsmn') -> int:
    """Get how many times a lô appeared on a given date for a region."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT count FROM lo_daily WHERE date = ? AND lo_number = ? AND region = ?',
        (date_str, lo_number, region)
    )
    row = cursor.fetchone()
    conn.close()
    return row['count'] if row else 0


def get_all_lo_status(region: str = 'xsmn'):
    """Get current status of all 100 lô numbers for a region."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM lo_status WHERE region = ? ORDER BY lo_number', (region,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_lo_status(lo_number: str, region: str = 'xsmn'):
    """Get current status of a specific lô number for a region."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM lo_status WHERE lo_number = ? AND region = ?', (lo_number, region))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_lo_status(lo_number: str, last_appeared_date: str,
                     days_since_last: int, consecutive_days: int,
                     current_limit: int, region: str = 'xsmn'):
    """Update the tracking status for a specific lô number in a region."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE lo_status 
        SET last_appeared_date = ?,
            days_since_last = ?,
            consecutive_days = ?,
            current_limit = ?,
            updated_at = ?
        WHERE lo_number = ? AND region = ?
    ''', (last_appeared_date, days_since_last, consecutive_days,
          current_limit, datetime.now().isoformat(), lo_number, region))
    conn.commit()
    conn.close()


def save_bet_record(date_str: str, lo_number: str, bet_amount: int,
                    is_win: bool, profit: int, region: str = 'xsmn'):
    """Save a bet record for P&L tracking."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO bet_history (date, lo_number, bet_amount, is_win, profit, region)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (date_str, lo_number, bet_amount, 1 if is_win else 0, profit, region))
    conn.commit()
    conn.close()


def get_bet_history(days: int = 30, region: str = 'xsmn'):
    """Get bet history for the last N days for a region."""
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT * FROM bet_history 
        WHERE date >= ? AND region = ?
        ORDER BY date DESC, lo_number ASC
    ''', (cutoff, region))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_results_for_date(date_str: str, region: str = None):
    """Get all lottery results for a specific date, optionally filtered by region."""
    conn = get_connection()
    cursor = conn.cursor()
    if region:
        cursor.execute('''
            SELECT * FROM lottery_results 
            WHERE date = ? AND region = ?
            ORDER BY province, prize_type
        ''', (date_str, region))
    else:
        cursor.execute('''
            SELECT * FROM lottery_results 
            WHERE date = ? 
            ORDER BY region, province, prize_type
        ''', (date_str,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_results_history(days: int = 30, region: str = 'xsmn'):
    """Get lottery results for the last N days for a region."""
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT date, lo_number, SUM(count) as total_count 
        FROM lo_daily 
        WHERE date >= ? AND region = ?
        GROUP BY date, lo_number
        ORDER BY date DESC
    ''', (cutoff, region))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_scraped_dates(region: str = None):
    """Get list of all scraped dates, optionally filtered by region."""
    conn = get_connection()
    cursor = conn.cursor()
    if region:
        cursor.execute('SELECT date, region FROM scraped_dates WHERE region = ? ORDER BY date DESC', (region,))
    else:
        cursor.execute('SELECT date, region FROM scraped_dates ORDER BY date DESC')
    rows = cursor.fetchall()
    conn.close()
    return [{'date': row['date'], 'region': row['region']} for row in rows]


def cleanup_old_data(days: int = 30):
    """Remove data older than N days to keep DB size manageable."""
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    total_deleted = 0
    cursor.execute('DELETE FROM lottery_results WHERE date < ?', (cutoff,))
    total_deleted += cursor.rowcount
    cursor.execute('DELETE FROM lo_daily WHERE date < ?', (cutoff,))
    total_deleted += cursor.rowcount
    cursor.execute('DELETE FROM bet_history WHERE date < ?', (cutoff,))
    total_deleted += cursor.rowcount
    cursor.execute('DELETE FROM scraped_dates WHERE date < ?', (cutoff,))
    total_deleted += cursor.rowcount

    conn.commit()
    conn.close()
    return total_deleted
