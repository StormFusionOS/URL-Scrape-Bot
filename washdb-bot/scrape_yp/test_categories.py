from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    page = context.new_page()
    
    # Try search with autocomplete hints
    page.goto('https://www.yellowpages.com', wait_until='domcontentloaded')
    time.sleep(2)
    
    # Type in search box to see suggestions
    try:
        search_box = page.query_selector('input[name="search_terms"]')
        if search_box:
            print("\nTrying 'deck':")
            search_box.fill('deck')
            time.sleep(1)
            suggestions = page.query_selector_all('.suggestion, .autocomplete-item, [class*="suggestion"]')
            for s in suggestions[:10]:
                print(f"  - {s.text_content()}")
            
            print("\nTrying 'pressure':")
            search_box.fill('pressure')
            time.sleep(1)
            suggestions = page.query_selector_all('.suggestion, .autocomplete-item, [class*="suggestion"]')
            for s in suggestions[:10]:
                print(f"  - {s.text_content()}")
                
            print("\nTrying 'window':")
            search_box.fill('window')
            time.sleep(1)
            suggestions = page.query_selector_all('.suggestion, .autocomplete-item, [class*="suggestion"]')
            for s in suggestions[:10]:
                print(f"  - {s.text_content()}")
    except Exception as e:
        print(f"Error: {e}")
    
    browser.close()
