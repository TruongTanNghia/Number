"""
Lottery Results Scraper - XSMN, XSMB & XSMT.
Crawls lottery results from:
  - xsmn.mobi   for Mien Nam    (Southern Vietnam)
  - xskt.com.vn for Mien Bac    (Northern Vietnam)  
  - xskt.com.vn for Mien Trung  (Central Vietnam)

HTML Structures:
  XSMN (xsmn.mobi): table.colgiai, td.txt-giai + td.v-giai
  XSMB (xskt.com.vn): table.result#MB0, td[title] + td>em/p
  XSMT (xskt.com.vn): table.tbl-xsmn#MT0, multi-column (like XSMN)
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time
import re
from database import save_lottery_results, is_date_scraped

# ═══════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════

XSMN_BASE_URL = "https://xsmn.mobi"
XSKT_BASE_URL = "https://xskt.com.vn"
ALL_REGIONS = ('xsmn', 'xsmb', 'xsmt')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
}

# Prize type label mappings (normalize)
PRIZE_PATTERNS = [
    (r'(?:G\.?\s*)?(?:DB|ĐB|Đặc biệt|đặc biệt)', 'G.DB'),
    (r'G\.?\s*8', 'G.8'), (r'G\.?\s*7', 'G.7'), (r'G\.?\s*6', 'G.6'),
    (r'G\.?\s*5', 'G.5'), (r'G\.?\s*4', 'G.4'), (r'G\.?\s*3', 'G.3'),
    (r'G\.?\s*2', 'G.2'), (r'G\.?\s*1', 'G.1'),
]

# Known provinces per region
XSMT_PROVINCES = [
    'Thừa Thiên Huế', 'Huế', 'Đà Nẵng', 'Khánh Hòa', 'Bình Định',
    'Quảng Bình', 'Quảng Trị', 'Quảng Nam', 'Quảng Ngãi', 'Ninh Thuận',
    'Phú Yên', 'Gia Lai', 'Đắk Lắk', 'Đắk Nông', 'Kon Tum',
]


# ═══════════════════════════════════════════════════════════
# COMMON UTILITIES
# ═══════════════════════════════════════════════════════════

def fetch_page(url: str, retries: int = 3) -> str:
    """Fetch HTML content from URL with retries."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            return resp.text
        except requests.RequestException as e:
            print(f"[Scraper] Attempt {attempt+1}/{retries} failed for {url}: {e}")
            if attempt < retries - 1:
                time.sleep(2)
    return None


def _norm_prize(label: str) -> str:
    """Normalize prize type labels."""
    if not label:
        return None
    label = label.strip()
    for pattern, result in PRIZE_PATTERNS:
        if re.match(pattern, label, re.IGNORECASE):
            return result
    return None


def _extract_numbers_from_cell(cell) -> list:
    """Extract all lottery numbers from a table cell (multi-method)."""
    numbers = []
    # Method 1: child elements (div, span, p, em)
    for elem in cell.find_all(['div', 'span', 'p', 'em']):
        if elem.find(['div', 'span', 'p', 'em']):
            continue  # skip containers
        text = elem.get_text(strip=True)
        if text and text.isdigit() and len(text) >= 2:
            numbers.append(text)
    # Method 2: direct text split
    if not numbers:
        text = cell.get_text(strip=True)
        for part in re.split(r'[\s,\-;]+', text):
            part = part.strip()
            if part and part.isdigit() and len(part) >= 2:
                numbers.append(part)
    # Method 3: regex
    if not numbers:
        found = re.findall(r'\b(\d{2,6})\b', cell.get_text())
        numbers = [n for n in found if len(n) >= 2]
    return numbers


# ═══════════════════════════════════════════════════════════
# XSMN SCRAPER (Mien Nam) - xsmn.mobi
# ═══════════════════════════════════════════════════════════

def parse_xsmn_results_page(html: str) -> dict:
    """Parse XSMN page from xsmn.mobi (multi-province table)."""
    soup = BeautifulSoup(html, 'html.parser')
    results = {}
    tables = soup.find_all('table', class_='colgiai')
    if not tables:
        tables = soup.find_all('table', class_=re.compile(r'colgiai'))
    for table in tables:
        _parse_multi_province_table(table, results)
    return results


def _parse_multi_province_table(table, results: dict):
    """Parse a multi-province table (XSMN / XSMT style from xsmn.mobi)."""
    rows = table.find_all('tr')
    if not rows:
        return

    # Extract province names from header
    provinces = []
    header_row = table.find('tr', class_='header')
    if header_row:
        for th in header_row.find_all('th'):
            link = th.find('a')
            name = (link.get_text(strip=True) if link else th.get_text(strip=True))
            if name and not name.isdigit() and len(name) > 1:
                provinces.append(name)

    for p in provinces:
        if p not in results:
            results[p] = []

    # Extract prize data
    for row in rows:
        if 'header' in (row.get('class') or []):
            continue
        cells = row.find_all('td')
        if not cells:
            continue

        prize_cell = row.find('td', class_='txt-giai')
        if not prize_cell and len(cells) >= 2:
            prize_cell = cells[0]
        if not prize_cell:
            continue

        prize_type = _norm_prize(prize_cell.get_text(strip=True))
        if not prize_type:
            continue

        value_cells = row.find_all('td', class_='v-giai')
        if not value_cells:
            value_cells = cells[1:]

        for idx, cell in enumerate(value_cells):
            prov = provinces[idx] if idx < len(provinces) else f"Province_{idx+1}"
            for num in _extract_numbers_from_cell(cell):
                if prov not in results:
                    results[prov] = []
                results[prov].append({'prize_type': prize_type, 'number': num})


def scrape_xsmn_day(date: datetime) -> dict:
    """Scrape XSMN lottery results for a specific date."""
    date_str = date.strftime('%Y-%m-%d')
    if is_date_scraped(date_str, 'xsmn'):
        return None

    url = f"{XSMN_BASE_URL}/xsmn-{date.day}-{date.month}-{date.year}.html"
    print(f"[XSMN] Fetching {url}")
    html = fetch_page(url)
    if not html:
        return None

    results = parse_xsmn_results_page(html)
    if results:
        for prov, nums in results.items():
            save_lottery_results(date_str, prov, nums, region='xsmn')
        total = sum(len(v) for v in results.values())
        print(f"[XSMN] {date_str}: {len(results)} provinces, {total} numbers")
    else:
        print(f"[XSMN] {date_str}: No results")
    return results


# ═══════════════════════════════════════════════════════════
# XSMB SCRAPER (Mien Bac) - xskt.com.vn
# Structure: <table class="result" id="MB0">
#   <tr><td title="Giải ĐB">ĐB</td><td><em>08717</em></td>...</tr>
#   <tr><td title="Giải nhất">G1</td><td><p>01150</p></td>...</tr>
# ═══════════════════════════════════════════════════════════

def parse_xsmb_results_page(html: str) -> dict:
    """Parse XSMB results from xskt.com.vn using table.result#MB0."""
    soup = BeautifulSoup(html, 'html.parser')
    results = {'Mien Bac': []}

    # Find the XSMB results table: class="result", id starts with "MB"
    table = soup.find('table', class_='result', id=re.compile(r'^MB'))
    if not table:
        # Fallback: any table with class "result"
        table = soup.find('table', class_='result')
    if not table:
        print("[XSMB] Could not find table.result")
        return _xsmb_fallback_text(soup)

    rows = table.find_all('tr')
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 2:
            continue

        # First cell: prize label (has title attribute like "Giải ĐB")
        label_cell = cells[0]
        label_text = label_cell.get_text(strip=True)
        
        # Also check title attribute
        title_attr = label_cell.get('title', '')
        
        # Try to normalize
        prize_type = _norm_prize(label_text)
        if not prize_type and title_attr:
            prize_type = _norm_prize(title_attr)
        if not prize_type:
            # Try common XSMB labels
            label_map = {
                'ĐB': 'G.DB', 'DB': 'G.DB',
                'G1': 'G.1', 'G2': 'G.2', 'G3': 'G.3', 'G4': 'G.4',
                'G5': 'G.5', 'G6': 'G.6', 'G7': 'G.7',
            }
            prize_type = label_map.get(label_text)
        
        if not prize_type:
            continue

        # Second cell: numbers (wrapped in <em>, <p>, or plain text)
        number_cell = cells[1]
        numbers = _extract_numbers_from_cell(number_cell)
        
        for num in numbers:
            results['Mien Bac'].append({
                'prize_type': prize_type,
                'number': num
            })

    if len(results['Mien Bac']) < 15:
        print(f"[XSMB] Warning: only {len(results['Mien Bac'])} numbers from table (expected 27)")
        # Try text fallback to supplement
        fallback = _xsmb_fallback_text(soup)
        if fallback and len(fallback.get('Mien Bac', [])) > len(results['Mien Bac']):
            results = fallback

    return results


def _xsmb_fallback_text(soup) -> dict:
    """Fallback: extract XSMB numbers from page text."""
    results = {'Mien Bac': []}
    text = soup.get_text()

    # Find results section
    markers_start = ['Thứ 2\n', 'Thứ 3\n', 'Thứ 4\n', 'Thứ 5\n',
                     'Thứ 6\n', 'Thứ 7\n', 'CN\n', 'Chủ nhật\n']
    markers_end = ['XSMB 100 ngày', 'XSMB 30 ngày', 'Xem thống kê']

    start_pos = -1
    for m in markers_start:
        p = text.find(m)
        if p != -1:
            start_pos = p
            break
    if start_pos == -1:
        return results

    end_pos = len(text)
    for m in markers_end:
        p = text.find(m, start_pos)
        if p != -1 and p < end_pos:
            end_pos = p

    section = text[start_pos:end_pos]
    all_nums = re.findall(r'\b(\d{2,6})\b', section)
    if not all_nums:
        return results

    # XSMB: DB(1x5), G1(1x5), G2(2x5), G3(6x5), G4(4x4), G5(6x4), G6(3x3), G7(4x2)
    structure = [
        ('G.DB', 1, 5), ('G.1', 1, 5), ('G.2', 2, 5), ('G.3', 6, 5),
        ('G.4', 4, 4), ('G.5', 6, 4), ('G.6', 3, 3), ('G.7', 4, 2),
    ]
    idx = 0
    for prize, count, exp_len in structure:
        for _ in range(count):
            if idx >= len(all_nums):
                break
            num = all_nums[idx]
            if abs(len(num) - exp_len) <= 1:
                results['Mien Bac'].append({'prize_type': prize, 'number': num})
                idx += 1
            else:
                # Look ahead
                for la in range(idx, min(idx + 3, len(all_nums))):
                    if abs(len(all_nums[la]) - exp_len) <= 1:
                        results['Mien Bac'].append({'prize_type': prize, 'number': all_nums[la]})
                        idx = la + 1
                        break
                else:
                    results['Mien Bac'].append({'prize_type': prize, 'number': num})
                    idx += 1

    return results


def scrape_xsmb_day(date: datetime) -> dict:
    """Scrape XSMB lottery results for a specific date."""
    date_str = date.strftime('%Y-%m-%d')
    if is_date_scraped(date_str, 'xsmb'):
        return None

    url = f"{XSKT_BASE_URL}/xsmb/ngay-{date.day}-{date.month}-{date.year}"
    print(f"[XSMB] Fetching {url}")
    html = fetch_page(url)
    if not html:
        return None

    results = parse_xsmb_results_page(html)
    if results and results.get('Mien Bac'):
        for prov, nums in results.items():
            save_lottery_results(date_str, prov, nums, region='xsmb')
        total = len(results['Mien Bac'])
        lo_set = set(n['number'][-2:] for n in results['Mien Bac'])
        print(f"[XSMB] {date_str}: {total} numbers, {len(lo_set)} unique lo")
    else:
        print(f"[XSMB] {date_str}: No results")
    return results


# ═══════════════════════════════════════════════════════════
# XSMT SCRAPER (Mien Trung) - xskt.com.vn
# Structure: <table class="tbl-xsmn" id="MT0">
#   Multi-column like XSMN: each column is a province
# ═══════════════════════════════════════════════════════════

def parse_xsmt_results_page(html: str) -> dict:
    """Parse XSMT results from xskt.com.vn using table.tbl-xsmn#MT0."""
    soup = BeautifulSoup(html, 'html.parser')
    results = {}

    # Find XSMT table: class="tbl-xsmn" and id starts with "MT"
    table = soup.find('table', class_='tbl-xsmn', id=re.compile(r'^MT'))
    if not table:
        table = soup.find('table', class_='tbl-xsmn')
    if not table:
        # Fallback: look for any table that mentions MT provinces
        for t in soup.find_all('table'):
            txt = t.get_text()
            if any(p in txt for p in XSMT_PROVINCES[:5]):
                table = t
                break
    if not table:
        print("[XSMT] Could not find results table")
        return results

    rows = table.find_all('tr')
    if not rows:
        return results

    # Step 1: Extract province names from header row(s)
    provinces = []
    for row in rows:
        ths = row.find_all('th')
        if ths:
            for th in ths:
                link = th.find('a')
                name = (link.get_text(strip=True) if link else th.get_text(strip=True))
                if name and not name.isdigit() and len(name) > 1:
                    # Check if it's a known province or province-like text
                    # Skip generic labels like "Giải", "ĐB", day names
                    skip = ['Giải', 'ĐB', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8',
                            'Thứ', 'XSMT', 'XS']
                    if not any(s in name for s in skip):
                        provinces.append(name)
            if provinces:
                break  # Found header row

    if not provinces:
        print("[XSMT] No provinces found in table header")
        return results

    for p in provinces:
        results[p] = []

    # Step 2: Extract prize data
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 2:
            continue

        # First cell: prize label
        label_text = cells[0].get_text(strip=True)
        title_attr = cells[0].get('title', '')
        prize_type = _norm_prize(label_text) or _norm_prize(title_attr)

        if not prize_type:
            # Try direct mapping
            label_map = {
                'ĐB': 'G.DB', 'DB': 'G.DB', 'G8': 'G.8',
                'G1': 'G.1', 'G2': 'G.2', 'G3': 'G.3', 'G4': 'G.4',
                'G5': 'G.5', 'G6': 'G.6', 'G7': 'G.7',
            }
            prize_type = label_map.get(label_text.replace('.', '').replace(' ', ''))
        
        if not prize_type:
            continue

        # Remaining cells: one per province
        value_cells = cells[1:]
        for idx, cell in enumerate(value_cells):
            if idx >= len(provinces):
                break
            prov = provinces[idx]
            for num in _extract_numbers_from_cell(cell):
                results[prov].append({'prize_type': prize_type, 'number': num})

    # Remove provinces with no results
    results = {k: v for k, v in results.items() if v}
    return results


def scrape_xsmt_day(date: datetime) -> dict:
    """Scrape XSMT lottery results for a specific date."""
    date_str = date.strftime('%Y-%m-%d')
    if is_date_scraped(date_str, 'xsmt'):
        return None

    url = f"{XSKT_BASE_URL}/xsmt/ngay-{date.day}-{date.month}-{date.year}"
    print(f"[XSMT] Fetching {url}")
    html = fetch_page(url)
    if not html:
        return None

    results = parse_xsmt_results_page(html)
    if results:
        for prov, nums in results.items():
            save_lottery_results(date_str, prov, nums, region='xsmt')
        total = sum(len(v) for v in results.values())
        lo_set = set()
        for nums in results.values():
            for n in nums:
                lo_set.add(n['number'][-2:])
        print(f"[XSMT] {date_str}: {len(results)} provinces, {total} numbers, {len(lo_set)} unique lo")
    else:
        print(f"[XSMT] {date_str}: No results")
    return results


# ═══════════════════════════════════════════════════════════
# UNIFIED SCRAPE API
# ═══════════════════════════════════════════════════════════

def scrape_day(date: datetime, region: str = 'xsmn') -> dict:
    """Scrape lottery results for a date and region."""
    if region == 'xsmb':
        return scrape_xsmb_day(date)
    elif region == 'xsmt':
        return scrape_xsmt_day(date)
    return scrape_xsmn_day(date)


def scrape_range(start: datetime, end: datetime, region: str = 'xsmn', delay: float = 1.0) -> int:
    """Scrape a date range for one region."""
    count = 0
    current = start
    while current <= end:
        if scrape_day(current, region):
            count += 1
        current += timedelta(days=1)
        if delay > 0:
            time.sleep(delay)
    return count


def scrape_last_n_days(n: int = 30, region: str = 'xsmn', delay: float = 1.0) -> int:
    """Scrape last N days for a region."""
    end = datetime.now() - timedelta(days=1)
    start = end - timedelta(days=n - 1)
    return scrape_range(start, end, region, delay)


def scrape_today(region: str = 'xsmn') -> dict:
    """Scrape today's results."""
    return scrape_day(datetime.now(), region)


def scrape_all_regions_range(n: int = 30, delay: float = 1.5) -> dict:
    """Scrape last N days for ALL 3 regions."""
    counts = {}
    for region in ALL_REGIONS:
        print(f"\n=== Scraping {region.upper()} ({n} days) ===")
        counts[region] = scrape_last_n_days(n, region, delay)
    return counts


if __name__ == '__main__':
    from database import init_db
    init_db()
    yesterday = datetime.now() - timedelta(days=1)
    for region in ALL_REGIONS:
        print(f"\n{'='*60}\nTesting {region.upper()}...")
        result = scrape_day(yesterday, region)
        if result:
            for prov, nums in result.items():
                lo = sorted(set(n['number'][-2:] for n in nums))
                print(f"  {prov}: {len(nums)} prizes, Lo: {', '.join(lo[:10])}...")
