"""
XSMN Lottery Results Scraper.
Crawls lottery results from xsmn.mobi for Miền Nam (Southern Vietnam).

HTML Structure (xsmn.mobi):
- table.colgiai - main results table
- tr.header th a.colorLinkBlue - province names
- td.txt-giai - prize label (G8, G7, ..., ĐB)  
- td.v-giai - prize numbers (div/span children)
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time
import re
from database import save_lottery_results, is_date_scraped

# Constants
BASE_URL = "https://xsmn.mobi"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
}


def fetch_page(url: str, retries: int = 3) -> str:
    """Fetch HTML content from URL with retries."""
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return response.text
        except requests.RequestException as e:
            print(f"[Scraper] Attempt {attempt + 1}/{retries} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(2)
    return None


def parse_results_page(html: str) -> dict:
    """
    Parse a XSMN results page and extract all lottery numbers.
    
    xsmn.mobi structure:
    - table.colgiai (with .badai/.bondai/.haidai variants)
    - tr.header → th → province names
    - tr rows → td.txt-giai (prize label) + td.v-giai (numbers)
    
    Returns:
        dict: {province_name: [{'prize_type': str, 'number': str}, ...]}
    """
    soup = BeautifulSoup(html, 'html.parser')
    results = {}

    # Find the main results table(s) with class 'colgiai'
    tables = soup.find_all('table', class_='colgiai')

    if not tables:
        # Fallback: try other possible class names
        tables = soup.find_all('table', class_=re.compile(r'colgiai|kqmn|result'))

    if not tables:
        print("[Scraper] No result tables found with class 'colgiai'")
        return results

    for table in tables:
        _parse_single_table(table, results)

    return results


def _parse_single_table(table, results: dict):
    """Parse a single result table and add to results dict."""
    rows = table.find_all('tr')
    if not rows:
        return

    # Step 1: Extract province names from header row
    provinces = []
    header_row = table.find('tr', class_='header')
    
    if header_row:
        # Province names are in <th> elements
        ths = header_row.find_all('th')
        for th in ths:
            link = th.find('a')
            if link:
                name = link.get_text(strip=True)
                if name and not name.isdigit():
                    provinces.append(name)
            else:
                name = th.get_text(strip=True)
                if name and not name.isdigit() and len(name) > 1:
                    provinces.append(name)
    
    if not provinces:
        # Fallback: look for any <th> with province-like text
        all_ths = table.find_all('th')
        province_names = [
            'TP HCM', 'TP Hồ Chí Minh', 'Đồng Tháp', 'Cà Mau', 'Bến Tre',
            'Vũng Tàu', 'Bạc Liêu', 'Đồng Nai', 'Cần Thơ', 'Sóc Trăng',
            'Tây Ninh', 'An Giang', 'Bình Thuận', 'Vĩnh Long', 'Bình Dương',
            'Trà Vinh', 'Long An', 'Bình Phước', 'Hậu Giang',
            'Tiền Giang', 'Kiên Giang', 'Đà Lạt'
        ]
        for th in all_ths:
            text = th.get_text(strip=True)
            for p in province_names:
                if p.lower() in text.lower():
                    provinces.append(p)
                    break

    # Initialize results for each province
    for province in provinces:
        if province not in results:
            results[province] = []

    # Step 2: Extract numbers from data rows
    for row in rows:
        if 'header' in (row.get('class') or []):
            continue

        cells = row.find_all('td')
        if not cells:
            continue

        # First cell with class 'txt-giai' is the prize label
        prize_cell = row.find('td', class_='txt-giai')
        if not prize_cell:
            # Try first td as fallback
            if len(cells) >= 2:
                prize_cell = cells[0]
            else:
                continue

        prize_text = prize_cell.get_text(strip=True)
        prize_type = _normalize_prize_type(prize_text)
        if not prize_type:
            continue

        # Get all value cells (td.v-giai)
        value_cells = row.find_all('td', class_='v-giai')
        
        if not value_cells:
            # Fallback: all cells except the first (prize label)
            value_cells = cells[1:]

        # Each value cell corresponds to a province (in order)
        for idx, cell in enumerate(value_cells):
            province = provinces[idx] if idx < len(provinces) else f"Province_{idx + 1}"
            
            # Extract numbers from the cell
            numbers = _extract_numbers_from_cell(cell)
            
            for num in numbers:
                if province not in results:
                    results[province] = []
                results[province].append({
                    'prize_type': prize_type,
                    'number': num
                })


def _extract_numbers_from_cell(cell) -> list:
    """Extract all lottery numbers from a table cell."""
    numbers = []
    
    # Method 1: Find all child elements (div, span) containing numbers
    child_elements = cell.find_all(['div', 'span'])
    for elem in child_elements:
        # Skip elements that are containers of other elements
        if elem.find(['div', 'span']):
            continue
        text = elem.get_text(strip=True)
        if text and text.isdigit() and len(text) >= 2:
            numbers.append(text)
    
    # Method 2: If no child elements found, try direct text
    if not numbers:
        text = cell.get_text(strip=True)
        # Split by whitespace, newlines, commas, dashes
        parts = re.split(r'[\s,\-;]+', text)
        for part in parts:
            part = part.strip()
            if part and part.isdigit() and len(part) >= 2:
                numbers.append(part)
    
    # Method 3: Regex fallback for any remaining numbers
    if not numbers:
        text = cell.get_text()
        found = re.findall(r'\b(\d{2,6})\b', text)
        numbers = [n for n in found if len(n) >= 2]
    
    return numbers


def _normalize_prize_type(label: str) -> str:
    """Normalize prize type labels to standard format."""
    if not label:
        return None
    
    label = label.strip()
    
    # Direct mappings (case-insensitive matching)
    patterns = [
        (r'(?:G\.?\s*)?(?:DB|ĐB)', 'G.ĐB'),
        (r'G\.?\s*8', 'G.8'),
        (r'G\.?\s*7', 'G.7'),
        (r'G\.?\s*6', 'G.6'),
        (r'G\.?\s*5', 'G.5'),
        (r'G\.?\s*4', 'G.4'),
        (r'G\.?\s*3', 'G.3'),
        (r'G\.?\s*2', 'G.2'),
        (r'G\.?\s*1', 'G.1'),
    ]
    
    for pattern, result in patterns:
        if re.match(pattern, label, re.IGNORECASE):
            return result
    
    return None


def scrape_day(date: datetime) -> dict:
    """
    Scrape lottery results for a specific date.
    
    Args:
        date: datetime object for the date to scrape
        
    Returns:
        dict: {province_name: [{'prize_type': str, 'number': str}, ...]}
    """
    date_str = date.strftime('%Y-%m-%d')

    # Check if already scraped
    if is_date_scraped(date_str):
        print(f"[Scraper] Date {date_str} already scraped, skipping")
        return None

    # Build URL: xsmn.mobi/xsmn-{d}-{m}-{yyyy}.html
    url = f"{BASE_URL}/xsmn-{date.day}-{date.month}-{date.year}.html"
    print(f"[Scraper] Fetching {url}")

    html = fetch_page(url)
    if not html:
        print(f"[Scraper] Failed to fetch {url}")
        return None

    results = parse_results_page(html)

    if results:
        # Save to database
        for province, numbers in results.items():
            save_lottery_results(date_str, province, numbers)
        
        total_numbers = sum(len(v) for v in results.values())
        total_lo = set()
        for numbers in results.values():
            for n in numbers:
                total_lo.add(n['number'][-2:])
        
        print(f"[Scraper] Saved {date_str}: {len(results)} provinces, "
              f"{total_numbers} numbers, {len(total_lo)} unique lo")
    else:
        print(f"[Scraper] WARNING: No results parsed for {date_str}")

    return results


def scrape_range(start_date: datetime, end_date: datetime, delay: float = 1.0) -> int:
    """
    Scrape lottery results for a date range.
    
    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        delay: Delay between requests in seconds
        
    Returns:
        int: Number of dates successfully scraped
    """
    count = 0
    current = start_date

    while current <= end_date:
        result = scrape_day(current)
        if result:
            count += 1
        current += timedelta(days=1)
        if delay > 0:
            time.sleep(delay)

    print(f"[Scraper] Scraped {count} days from {start_date.strftime('%Y-%m-%d')} "
          f"to {end_date.strftime('%Y-%m-%d')}")
    return count


def scrape_last_n_days(n: int = 30, delay: float = 1.0) -> int:
    """Scrape the last N days of results."""
    end_date = datetime.now() - timedelta(days=1)  # Yesterday (today may not have results yet)
    start_date = end_date - timedelta(days=n - 1)
    return scrape_range(start_date, end_date, delay)


def scrape_today() -> dict:
    """Scrape today's results."""
    return scrape_day(datetime.now())


if __name__ == '__main__':
    # Test scraping
    from database import init_db
    init_db()
    
    print("Testing scraper with yesterday's results...")
    yesterday = datetime.now() - timedelta(days=1)
    result = scrape_day(yesterday)
    
    if result:
        print(f"\nFound {len(result)} provinces:")
        for province, numbers in result.items():
            lo_set = sorted(set(n['number'][-2:] for n in numbers))
            print(f"  {province.encode('ascii', 'replace').decode()}: {len(numbers)} prizes")
            print(f"    Lo to: {', '.join(lo_set)}")
    else:
        print("No results found")
