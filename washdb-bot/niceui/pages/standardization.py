"""
Standardization page - Manage company data enrichment with live websocket updates.

Features:
- Real-time statistics with auto-refresh
- Live batch processing with progress updates (LLM + Stealth browser)
- Manual company editing
- Activity log with websocket updates
"""

import asyncio
import os
import re
import httpx
from datetime import datetime
from nicegui import ui
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Ollama LLM for name extraction
OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2:3b"


def extract_name_with_llm(title: str, domain: str, original_name: str) -> str:
    """Use local LLM (Ollama) to extract business name from page title."""
    prompt = f"""You are extracting business names from website titles for a pressure washing/cleaning company database.

TASK: Extract the COMPLETE business name from this title.

INPUT:
- Title: "{title}"
- Domain: {domain}
- Current DB name: "{original_name}"

UNDERSTANDING BUSINESS NAMES:

1. Many businesses have service words IN their name - this is VALID:
   - "River City Pressure Washing" - full business name (includes location + service)
   - "Austin Power Wash" - full business name (includes city + service)
   - "Lone Star Soft Wash" - full business name (includes branded term + service)
   - "Mike's Pressure Washing" - full business name (person's name + service)
   - "Elite Exterior Cleaning" - full business name (adjective + service)

2. What is NOT a business name (just generic descriptions):
   - "Pressure Washing Services" - no unique identifier
   - "Soft Washing Dallas" - just service + city, no business identity
   - "Professional Cleaning" - too generic
   - "Home", "Contact Us", "About" - navigation pages

3. The KEY difference:
   - BUSINESS NAME = has a unique/branded element (person name, location name, creative word)
   - NOT A NAME = just describes the service with no unique identifier

TITLE PATTERNS:
- "Service in City | BUSINESS NAME" → extract the business name after |
- "BUSINESS NAME | Service Description" → extract before |
- "Home | BUSINESS NAME" → ignore "Home", take what's after |
- "Welcome to BUSINESS NAME" → remove "Welcome to"

EXAMPLES (study carefully - notice how service words ARE part of names):
Title: "Pressure Washing San Antonio | River City Pressure Washing" → River City Pressure Washing
Title: "Home | Mike's Power Washing" → Mike's Power Washing
Title: "Austin Soft Wash | Residential & Commercial" → Austin Soft Wash
Title: "Lone Star Exterior Cleaning - Home" → Lone Star Exterior Cleaning
Title: "Welcome to Elite Pressure Pros" → Elite Pressure Pros
Title: "Squeaky Clean Window Washing | Dallas Fort Worth" → Squeaky Clean Window Washing
Title: "Pressure Washing Omaha | Hydro Softwash" → Hydro Softwash
Title: "BlueWave Softwash | Soft Washing & Pressure Washing" → BlueWave Softwash
Title: "Pressure Washing Services" → NONE (no unique identifier)
Title: "Professional Cleaning Dallas" → NONE (too generic)
Title: "Contact Us | ABC Company" → ABC Company

NOW EXTRACT FROM: "{title}"
- Include the FULL business name even if it contains service words
- Look for unique identifiers (names, locations, creative words)
- Remove LLC/Inc/Co suffixes
- If truly no business name exists, return: NONE

ANSWER (just the name):"""

    try:
        response = httpx.post(
            OLLAMA_URL,
            json={
                "model": LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 50,
                }
            },
            timeout=30.0
        )

        if response.status_code == 200:
            result = response.json()
            name = result.get("response", "").strip()

            # Clean up the response
            name = name.strip('"\'')
            name = re.sub(r'^(Business name:|Name:|The business name is:?)\s*', '', name, flags=re.IGNORECASE)
            name = name.strip()

            # Validate
            if name.upper() == "NONE" or len(name) < 3 or len(name) > 60:
                return None
            if name.lower() in ['none', 'n/a', 'unknown', 'not found']:
                return None

            return name
    except Exception as e:
        print(f"LLM extraction error: {e}")

    return None


def get_engine():
    """Get database engine"""
    return create_engine(os.getenv('DATABASE_URL'))


class StandardizationPageState:
    """State for the standardization page."""
    def __init__(self):
        self.stats = {}
        self.pending_companies = []
        self.worker_running = False
        self.worker_stats = {'processed': 0, 'success': 0, 'failed': 0}
        self.log_messages = []
        self.current_company = None
        self.update_timer = None

        # UI element references
        self.stats_container = None
        self.pending_container = None
        self.activity_container = None
        self.log_container = None
        self.progress_label = None
        self.progress_bar = None
        self.run_btn = None
        self.stop_btn = None


page_state = StandardizationPageState()


def get_statistics():
    """Get standardization statistics"""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                standardization_status,
                COUNT(*) as count
            FROM companies
            WHERE verified = TRUE
            GROUP BY standardization_status
        """))

        stats = {
            'pending': 0,
            'in_progress': 0,
            'completed': 0,
            'failed': 0,
            'skipped': 0,
            'total': 0
        }

        for row in result:
            status = row[0] or 'pending'
            count = row[1]
            if status in stats:
                stats[status] = count
            stats['total'] += count

        if stats['total'] > 0:
            stats['completion_percent'] = round(
                (stats['completed'] / stats['total']) * 100, 1
            )
        else:
            stats['completion_percent'] = 0

        return stats


def get_pending_companies(limit=15, priority='poor_names'):
    """Get pending companies (NULL or 'pending' status)"""
    order_by = {
        'poor_names': 'name_quality_score ASC NULLS FIRST, id',
        'newest': 'verified_at DESC NULLS LAST, id',
        'oldest': 'verified_at ASC NULLS LAST, id'
    }.get(priority, 'name_quality_score ASC NULLS FIRST, id')

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(f"""
            SELECT
                id, name, domain, address, phone, email,
                name_quality_score, standardization_status
            FROM companies
            WHERE verified = TRUE
            AND (standardization_status IS NULL OR standardization_status = 'pending')
            AND domain IS NOT NULL
            AND domain != ''
            ORDER BY {order_by}
            LIMIT :limit
        """), {'limit': limit})

        return [dict(row._mapping) for row in result]


def get_recent_activity(limit=10):
    """Get recent standardization activity"""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                id, name, standardized_name,
                standardized_name_source, standardization_status,
                standardized_at, name_quality_score
            FROM companies
            WHERE standardized_at IS NOT NULL
            ORDER BY standardized_at DESC
            LIMIT :limit
        """), {'limit': limit})

        return [dict(row._mapping) for row in result]


def update_standardization(company_id, standardized_name=None, source='manual',
                          confidence=1.0, city=None, state=None, zip_code=None,
                          status='completed'):
    """Update standardization for a company"""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE companies
            SET
                standardized_name = COALESCE(:std_name, standardized_name),
                standardized_name_source = CASE
                    WHEN :std_name IS NOT NULL THEN :source
                    ELSE standardized_name_source
                END,
                standardized_name_confidence = CASE
                    WHEN :std_name IS NOT NULL THEN :confidence
                    ELSE standardized_name_confidence
                END,
                city = COALESCE(:city, city),
                state = COALESCE(:state, state),
                zip_code = COALESCE(:zip_code, zip_code),
                standardization_status = :status,
                standardized_at = NOW()
            WHERE id = :id
        """), {
            'id': company_id,
            'std_name': standardized_name,
            'source': source,
            'confidence': confidence,
            'city': city,
            'state': state,
            'zip_code': zip_code,
            'status': status
        })
        conn.commit()


def mark_status(company_id, status):
    """Mark company status"""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE companies
            SET standardization_status = :status,
                standardized_at = NOW()
            WHERE id = :id
        """), {'id': company_id, 'status': status})
        conn.commit()


def bulk_mark_good_names(min_score=80):
    """Mark companies with good names as complete"""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE companies
            SET standardization_status = 'completed',
                standardized_at = NOW()
            WHERE verified = TRUE
            AND standardization_status = 'pending'
            AND name_quality_score >= :min_score
        """), {'min_score': min_score})
        conn.commit()
        return result.rowcount


def get_company_details(company_id):
    """Get company details for editing"""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, name, domain, address, phone, email,
                   city, state, zip_code, standardized_name,
                   standardized_name_source, name_quality_score
            FROM companies WHERE id = :id
        """), {'id': company_id})
        row = result.fetchone()
        return dict(row._mapping) if row else None


def format_number(n):
    return f"{n:,}"


def get_quality_color(score):
    if score < 30:
        return 'red'
    elif score < 60:
        return 'orange'
    elif score < 80:
        return 'blue'
    return 'green'


def clean_title(title):
    """Clean website title to extract business name"""
    if not title:
        return ""
    cleaned = title.strip()
    generic_titles = ['home', 'welcome', 'homepage', 'official site']
    if cleaned.lower() in generic_titles:
        return ""

    patterns = [
        r'\s*[\|\-\u2013\u2014]\s*Home\s*$',
        r'\s*[\|\-\u2013\u2014]\s*Welcome\s*$',
        r'\s*-\s*$',
        r'\s*\|\s*$',
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    separators = [' | ', ' - ', ' \u2013 ', ' \u2014 ', ' :: ']
    for sep in separators:
        if sep in cleaned:
            parts = cleaned.split(sep)
            valid_parts = [p.strip() for p in parts
                         if p.strip().lower() not in generic_titles
                         and len(p.strip()) >= 3]
            if valid_parts:
                cleaned = valid_parts[0]
            break

    if len(cleaned) > 60:
        return ""
    return cleaned.strip()


def score_name_quality(name):
    """Calculate name quality score (0-100)"""
    if not name:
        return 0
    score = 50
    length = len(name)
    if length < 3:
        score -= 50
    elif length < 5:
        score -= 30
    elif length < 8:
        score -= 10
    elif length >= 15:
        score += 20
    elif length >= 10:
        score += 10

    words = name.split()
    if len(words) >= 3:
        score += 15
    elif len(words) >= 2:
        score += 5

    if any(c.isupper() for c in name):
        score += 5
    if name.isupper() and len(name) > 3:
        score -= 10

    return max(0, min(100, score))


def parse_location_from_address(address):
    """Parse city, state, zip from address"""
    result = {'city': None, 'state': None, 'zip_code': None}
    if not address:
        return result

    patterns = [
        r'([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)',
        r'([A-Za-z\s]+),\s*([A-Za-z]+)\s*(\d{5}(?:-\d{4})?)',
        r'([A-Za-z\s]+),\s*([A-Z]{2})\s*$',
    ]

    for pattern in patterns:
        match = re.search(pattern, address)
        if match:
            result['city'] = match.group(1).strip()
            result['state'] = match.group(2).strip()
            if len(match.groups()) > 2:
                result['zip_code'] = match.group(3)
            break

    return result


def get_stealth_driver():
    """Get SeleniumBase stealth browser driver."""
    try:
        from seleniumbase import Driver
        driver = Driver(
            uc=True,  # Undetected ChromeDriver mode
            headless=False,  # Headed for better stealth (hidden via xvfb)
            locale_code="en",
        )
        driver.set_page_load_timeout(20)
        return driver
    except Exception as e:
        print(f"Failed to init stealth browser: {e}")
        return None


def fetch_title_stealth(driver, url: str) -> str:
    """Fetch page title using stealth browser."""
    import time

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        driver.get(url)
        time.sleep(2)  # Wait for JS/Cloudflare
        title = driver.title

        # Try og:title if main title is empty
        if not title or title.lower() in ['', 'untitled', 'home']:
            try:
                og_title = driver.find_element("css selector", 'meta[property="og:title"]')
                if og_title:
                    title = og_title.get_attribute('content')
            except:
                pass

        return title if title else None
    except Exception as e:
        log_msg(f"  Stealth fetch error: {str(e)[:40]}")
        return None


async def run_batch_processing(batch_size):
    """Run batch processing with SeleniumBase stealth browser + LLM"""
    page_state.worker_running = True
    page_state.worker_stats = {'processed': 0, 'success': 0, 'failed': 0}
    page_state.log_messages = []

    companies = get_pending_companies(limit=batch_size, priority='poor_names')

    if not companies:
        page_state.worker_running = False
        ui.notify('No pending companies to process', type='info')
        return

    log_msg(f"Starting batch of {len(companies)} companies (SeleniumBase + LLM)")

    if page_state.run_btn:
        page_state.run_btn.disable()
    if page_state.stop_btn:
        page_state.stop_btn.enable()

    driver = None
    try:
        # Initialize stealth browser
        log_msg("Initializing stealth browser (UC mode)...")
        driver = get_stealth_driver()

        if not driver:
            log_msg("ERROR: Could not initialize stealth browser")
            ui.notify('Failed to start stealth browser', type='negative')
            return

        log_msg("Stealth browser ready")

        for company in companies:
            if not page_state.worker_running:
                log_msg("Batch stopped by user")
                break

            await process_company_stealth(driver, company)

            # Update progress
            if page_state.progress_label:
                page_state.progress_label.set_text(
                    f"Processing: {page_state.current_company or '...'} "
                    f"({page_state.worker_stats['processed']}/{len(companies)})"
                )
            if page_state.progress_bar:
                page_state.progress_bar.set_value(
                    page_state.worker_stats['processed'] / len(companies)
                )

            await asyncio.sleep(0.5)  # Small delay between requests

    except Exception as e:
        log_msg(f"Error: {str(e)}")
    finally:
        # Close stealth browser
        if driver:
            try:
                driver.quit()
                log_msg("Stealth browser closed")
            except:
                pass

        page_state.worker_running = False
        page_state.current_company = None

        if page_state.run_btn:
            page_state.run_btn.enable()
        if page_state.stop_btn:
            page_state.stop_btn.disable()
        if page_state.progress_label:
            page_state.progress_label.set_text('Ready')
        if page_state.progress_bar:
            page_state.progress_bar.set_value(0)

        stats = page_state.worker_stats
        log_msg(f"Batch complete: {stats['processed']} processed, {stats['success']} success, {stats['failed']} failed")
        ui.notify(
            f"Batch complete! Processed: {stats['processed']}, Success: {stats['success']}, Failed: {stats['failed']}",
            type='positive'
        )


async def process_company_stealth(driver, company):
    """Process a single company using SeleniumBase stealth browser + LLM"""
    company_id = company['id']
    name = company['name']
    domain = company['domain']
    address = company.get('address')
    current_score = company.get('name_quality_score', 50)

    page_state.current_company = name
    log_msg(f"Processing: {name}")

    mark_status(company_id, 'in_progress')

    location = parse_location_from_address(address) if address else {}
    city = location.get('city')
    state = location.get('state')
    zip_code = location.get('zip_code')

    if current_score >= 80:
        update_standardization(company_id, city=city, state=state, zip_code=zip_code, status='completed')
        log_msg(f"  Good name quality ({current_score}), marked complete")
        page_state.worker_stats['processed'] += 1
        page_state.worker_stats['success'] += 1
        return

    new_name = None
    source = None
    confidence = 0.0

    if domain:
        url = f"https://{domain}" if not domain.startswith('http') else domain
        log_msg(f"  Fetching (stealth): {url}")

        # Use stealth browser to fetch title
        title = fetch_title_stealth(driver, url)

        if title:
            log_msg(f"  Title: '{title[:50]}...'")
            # Use LLM for intelligent name extraction
            llm_name = extract_name_with_llm(title, domain, name)
            if llm_name:
                new_name = llm_name
                source = 'llm_stealth'
                confidence = 0.92
                log_msg(f"  LLM extracted: '{new_name}'")
            else:
                # Fallback to simple regex cleaning
                cleaned = clean_title(title)
                new_score = score_name_quality(cleaned)
                if cleaned and new_score > current_score:
                    new_name = cleaned
                    source = 'stealth_regex'
                    confidence = 0.80
                    log_msg(f"  Regex fallback: '{cleaned}' (score: {new_score})")

    update_standardization(
        company_id,
        standardized_name=new_name,
        source=source or 'none',
        confidence=confidence,
        city=city,
        state=state,
        zip_code=zip_code,
        status='completed'
    )

    page_state.worker_stats['processed'] += 1
    if new_name:
        log_msg(f"  Updated name: '{new_name}'")
        page_state.worker_stats['success'] += 1
    else:
        log_msg(f"  No improvement found")
        page_state.worker_stats['success'] += 1


def log_msg(message):
    """Add log message"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    page_state.log_messages.append(f"[{timestamp}] {message}")
    if len(page_state.log_messages) > 100:
        page_state.log_messages = page_state.log_messages[-100:]


def stop_batch():
    """Stop batch processing"""
    page_state.worker_running = False
    ui.notify('Stopping batch...', type='warning')


def open_edit_dialog(company):
    """Open edit dialog for a company"""
    details = get_company_details(company['id'])
    if not details:
        ui.notify('Company not found', type='negative')
        return

    with ui.dialog() as dialog, ui.card().classes('w-[500px]'):
        ui.label(f"Edit: {details.get('name')}").classes('font-bold text-xl mb-4')

        std_name = ui.input(
            'Standardized Name',
            value=details.get('standardized_name', '')
        ).classes('w-full')

        with ui.row().classes('gap-2 w-full'):
            city = ui.input('City', value=details.get('city', '')).classes('flex-1')
            state = ui.input('State', value=details.get('state', '')).classes('w-20')
            zip_input = ui.input('Zip', value=details.get('zip_code', '')).classes('w-28')

        ui.separator().classes('my-4')

        with ui.row().classes('gap-2 justify-end'):
            ui.button('Cancel', on_click=dialog.close).props('flat')

            def save():
                update_standardization(
                    details['id'],
                    standardized_name=std_name.value if std_name.value else None,
                    source='manual',
                    confidence=1.0,
                    city=city.value if city.value else None,
                    state=state.value if state.value else None,
                    zip_code=zip_input.value if zip_input.value else None
                )
                ui.notify('Saved!', type='positive')
                dialog.close()

            ui.button('Save', on_click=save).props('color=primary')

    dialog.open()


def mark_complete(company):
    """Mark company as complete"""
    mark_status(company['id'], 'completed')
    ui.notify(f"Marked '{company.get('name')}' as complete", type='positive')


def skip_company(company):
    """Skip company"""
    mark_status(company['id'], 'skipped')
    ui.notify(f"Skipped '{company.get('name')}'", type='info')


async def do_mark_good_names():
    """Mark good names as complete"""
    count = bulk_mark_good_names(min_score=80)
    ui.notify(f"Marked {count} companies with good names as complete", type='positive')


def standardization_page():
    """Build the standardization page"""
    ui.label('Data Standardization').classes('text-2xl font-bold mb-4')
    ui.label('Enrich company records with better names and location data').classes('text-gray-500 mb-4')

    # Stats section
    with ui.card().classes('w-full mb-4'):
        ui.label('Statistics').classes('text-lg font-bold mb-2')

        @ui.refreshable
        def stats_section():
            stats = get_statistics()

            with ui.row().classes('gap-4 flex-wrap'):
                with ui.column().classes('items-center min-w-[120px]'):
                    ui.icon('business', size='lg').classes('text-blue-500')
                    ui.label(format_number(stats.get('total', 0))).classes('text-2xl font-bold')
                    ui.label('Total').classes('text-sm text-gray-500')

                with ui.column().classes('items-center min-w-[120px]'):
                    ui.icon('check_circle', size='lg').classes('text-green-500')
                    ui.label(format_number(stats.get('completed', 0))).classes('text-2xl font-bold text-green-600')
                    ui.label('Completed').classes('text-sm text-gray-500')

                with ui.column().classes('items-center min-w-[120px]'):
                    ui.icon('pending', size='lg').classes('text-orange-500')
                    ui.label(format_number(stats.get('pending', 0))).classes('text-2xl font-bold text-orange-600')
                    ui.label('Pending').classes('text-sm text-gray-500')

                with ui.column().classes('items-center min-w-[120px]'):
                    ui.icon('error', size='lg').classes('text-red-500')
                    ui.label(format_number(stats.get('failed', 0))).classes('text-2xl font-bold text-red-600')
                    ui.label('Failed').classes('text-sm text-gray-500')

            # Progress bar
            total = stats.get('total', 0)
            completed = stats.get('completed', 0)
            if total > 0:
                ui.linear_progress(value=completed/total).classes('mt-4')
                ui.label(f"{stats.get('completion_percent', 0)}% Complete").classes('text-lg font-bold mt-2')

        stats_section()

        ui.button('Refresh Stats', icon='refresh', on_click=stats_section.refresh).classes('mt-2')

    # Batch processing card
    with ui.card().classes('w-full mb-4'):
        ui.label('Batch Processing').classes('text-lg font-bold mb-2')

        with ui.row().classes('items-center gap-4 mb-4'):
            batch_size = ui.number('Batch Size', value=50, min=10, max=200).classes('w-32')
            page_state.run_btn = ui.button('Run Batch', icon='play_arrow',
                on_click=lambda: asyncio.create_task(run_batch_processing(int(batch_size.value))))
            page_state.stop_btn = ui.button('Stop', icon='stop', on_click=stop_batch).props('color=red')
            page_state.stop_btn.disable()

        page_state.progress_label = ui.label('Ready').classes('text-sm text-gray-500')
        page_state.progress_bar = ui.linear_progress(value=0).classes('w-full')

        ui.separator().classes('my-4')

        ui.label('Quick Actions').classes('font-bold mb-2')
        ui.button(
            'Mark Good Names Complete (80+)',
            icon='done_all',
            on_click=lambda: asyncio.create_task(do_mark_good_names())
        ).props('color=secondary')

        ui.separator().classes('my-4')

        # Log area
        ui.label('Processing Log').classes('font-bold mb-2')
        with ui.scroll_area().classes('w-full h-40 bg-gray-100 rounded p-2'):
            @ui.refreshable
            def log_area():
                if not page_state.log_messages:
                    ui.label('No log messages yet...').classes('text-gray-500 text-sm')
                else:
                    with ui.column().classes('font-mono text-xs'):
                        for msg in page_state.log_messages[-15:]:
                            ui.label(msg).classes('text-gray-700')
            log_area()

        # Auto-refresh log every 2 seconds during processing
        ui.timer(2.0, lambda: log_area.refresh() if page_state.worker_running else None)

    # Two column layout
    with ui.row().classes('w-full gap-4'):
        # Pending companies
        with ui.column().classes('flex-1'):
            with ui.card().classes('w-full'):
                ui.label('Pending Companies').classes('text-lg font-bold mb-2')
                ui.badge('Worst names first', color='orange').classes('mb-2')

                @ui.refreshable
                def pending_section():
                    companies = get_pending_companies(limit=12)

                    if not companies:
                        with ui.column().classes('items-center p-4'):
                            ui.icon('check_circle', size='xl').classes('text-green-500')
                            ui.label('All companies standardized!').classes('text-lg')
                        return

                    for company in companies:
                        with ui.card().classes('w-full mb-2'):
                            with ui.row().classes('items-center gap-2 w-full'):
                                score = company.get('name_quality_score', 50)
                                ui.badge(str(score), color=get_quality_color(score)).classes('text-sm')

                                with ui.column().classes('flex-1'):
                                    ui.label(company.get('name', 'Unknown')).classes('font-bold')
                                    if company.get('domain'):
                                        ui.link(company['domain'], f"https://{company['domain']}",
                                               new_tab=True).classes('text-blue-500 text-xs')

                                with ui.row().classes('gap-1'):
                                    ui.button(icon='edit', on_click=lambda c=company: open_edit_dialog(c)).props('flat round dense')
                                    ui.button(icon='check', on_click=lambda c=company: [mark_complete(c), pending_section.refresh()]).props('flat round dense color=green')
                                    ui.button(icon='skip_next', on_click=lambda c=company: [skip_company(c), pending_section.refresh()]).props('flat round dense color=orange')

                pending_section()

                ui.button('Refresh', icon='refresh', on_click=pending_section.refresh).classes('mt-2')

        # Recent activity
        with ui.column().classes('w-80'):
            with ui.card().classes('w-full'):
                ui.label('Recent Activity').classes('text-lg font-bold mb-2')

                @ui.refreshable
                def activity_section():
                    activities = get_recent_activity(limit=10)

                    if not activities:
                        ui.label('No recent activity').classes('text-gray-500')
                        return

                    for act in activities:
                        with ui.row().classes('w-full items-center gap-2 py-1 border-b'):
                            status = act.get('standardization_status', 'pending')
                            if status == 'completed':
                                ui.icon('check_circle', size='xs').classes('text-green-500')
                            elif status == 'failed':
                                ui.icon('error', size='xs').classes('text-red-500')
                            else:
                                ui.icon('pending', size='xs').classes('text-orange-500')

                            name = act.get('standardized_name') or act.get('name', 'Unknown')
                            ui.label(name[:25] + '...' if len(name) > 25 else name).classes('flex-1 text-sm')

                            source = act.get('standardized_name_source', '')
                            if source:
                                ui.badge(source[:8], color='blue').classes('text-xs')

                activity_section()

                ui.button('Refresh', icon='refresh', on_click=activity_section.refresh).classes('mt-2')

    # Auto-refresh stats every 30 seconds
    ui.timer(30.0, lambda: stats_section.refresh())
