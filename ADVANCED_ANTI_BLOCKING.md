# Advanced Anti-Blocking Strategies

This document outlines advanced techniques to avoid rate limiting and bot detection.

## ✅ Currently Implemented (Free)

### 1. **Long Delays with Randomization**
- Base delay: 10 seconds per request
- ±20% jitter (8-12 seconds actual)
- State cooldown: 15-25 seconds between states

### 2. **Browser Fingerprint Randomization**
- Random viewport sizes (1920x1080, 1366x768, etc.)
- Random user agents (Chrome, Firefox, Safari)
- Random timezones (EST, CST, MST, PST)
- Random locales (en-US, en-GB, en-CA)
- WebDriver property masking

### 3. **Human Behavior Simulation**
- Random scrolling patterns
- Random mouse movements
- Variable page wait times (1-3 seconds)

### 4. **Request Header Randomization**
- Rotating Accept-Language headers
- DNT (Do Not Track) enabled
- Realistic Accept-Encoding

## 🚀 Advanced Options (Requires External Services)

### Option 1: Residential Proxy Rotation ⭐ MOST EFFECTIVE

**What it does:** Routes each request through a different residential IP address

**Services:**
- **Bright Data (formerly Luminati)**: $500+/month
  - https://brightdata.com
  - Best quality, expensive

- **Smartproxy**: $75+/month
  - https://smartproxy.com
  - Good balance of price/quality

- **Oxylabs**: $300+/month
  - https://oxylabs.io
  - High quality

- **IPRoyal**: $7/GB
  - https://iproyal.com
  - Budget option

**Implementation:**
```python
# In yp_client.py, add proxy to Playwright context:
context = browser.new_context(
    proxy={
        'server': 'http://proxy-server:port',
        'username': 'your-username',
        'password': 'your-password'
    },
    # ... other settings
)
```

**Pros:**
- Nearly eliminates rate limiting (each request = different IP)
- Looks like organic traffic
- Can scrape 10x-100x faster

**Cons:**
- Expensive ($75-$500+/month)
- Requires account setup
- Some proxies can be slow

---

### Option 2: Distributed Scraping (VPS Network)

**What it does:** Run scrapers on multiple VPS instances in different locations

**Services:**
- **DigitalOcean**: $4-6/month per droplet
- **Linode**: $5/month per instance
- **Vultr**: $3.50/month per instance

**Setup:**
1. Create 5-10 VPS instances in different regions
2. Deploy your scraper to each
3. Split the state list across instances
4. Each scraper handles 5-10 states

**Pros:**
- Moderate cost ($20-50/month for 5-10 instances)
- Each instance has unique IP
- Good for large-scale scraping

**Cons:**
- Requires DevOps knowledge
- Need to manage multiple instances
- Still slower than proxies

---

### Option 3: CAPTCHA Solving Services

**What it does:** Automatically solves CAPTCHAs if Yellow Pages starts serving them

**Services:**
- **2Captcha**: $2.99/1000 solves
  - https://2captcha.com

- **Anti-Captcha**: $2.00/1000 solves
  - https://anti-captcha.com

**Implementation:**
```python
from playwright.sync_api import sync_playwright
from twocaptcha import TwoCaptcha

solver = TwoCaptcha('your-api-key')

# When CAPTCHA is detected:
if page.locator('iframe[src*="recaptcha"]').count() > 0:
    sitekey = page.locator('[data-sitekey]').get_attribute('data-sitekey')
    result = solver.recaptcha(sitekey=sitekey, url=url)
    page.evaluate(f"document.getElementById('g-recaptcha-response').innerHTML='{result['code']}'")
```

**Pros:**
- Cheap ($3/1000 CAPTCHAs)
- Only pay when needed

**Cons:**
- Only helpful if CAPTCHAs appear
- Adds 10-30 seconds per CAPTCHA

---

### Option 4: Scraping API Services (Easiest)

**What it does:** Use a service that handles all anti-bot measures for you

**Services:**
- **ScraperAPI**: $29-$249/month
  - https://scraperapi.com
  - Handles proxies, headers, CAPTCHAs automatically

- **Scrapingbee**: $49-$449/month
  - https://scrapingbee.com
  - Similar to ScraperAPI

**Implementation:**
```python
import requests

# Instead of Playwright, just use their API:
url = f"http://api.scraperapi.com?api_key=YOUR_KEY&url={target_url}"
response = requests.get(url)
html = response.text
```

**Pros:**
- Easiest to implement
- Handles everything (proxies, headers, JS rendering)
- Fixed monthly cost

**Cons:**
- Most expensive per request
- Less control
- Usage limits

---

## 🎯 Recommended Approach

### For Budget-Conscious ($0-20/month):
1. Use current implementation (delays + fingerprinting)
2. Run smaller batches (5-10 states at a time)
3. Run during off-peak hours (2am-6am)
4. Spread runs across multiple days

### For Speed + Budget ($50-100/month):
1. **Smartproxy residential proxies** ($75/month, 5GB)
2. Remove cooldown periods
3. Reduce delays to 3-5 seconds
4. Can scrape all 50 states in 1-2 hours

### For Maximum Speed ($200+/month):
1. **Bright Data proxies** + **ScraperAPI**
2. No delays needed
3. Parallel scraping (multiple categories simultaneously)
4. Can scrape all 50 states in 15-30 minutes

---

## 📊 Cost-Benefit Analysis

| Method | Monthly Cost | Time for 50 States | Detection Risk | Effort |
|--------|-------------|-------------------|----------------|---------|
| Current (Free) | $0 | 3-4 hours | Medium | Done ✓ |
| Residential Proxies | $75-500 | 1-2 hours | Very Low | Medium |
| Distributed VPS | $20-50 | 2-3 hours | Low | High |
| Scraping API | $50-250 | 30min-1hour | Very Low | Low |

---

## 💡 Quick Wins (Free)

If you don't want to pay for services, try these:

### 1. **Schedule During Off-Peak Hours**
Run discovery at 2am-6am EST when YP traffic is lowest

### 2. **Batch by State**
Instead of all 50 states, do:
- Monday: AL, AK, AZ, AR, CA (5 states)
- Tuesday: CO, CT, DE, FL, GA (5 states)
- etc.

### 3. **Use Only Top Categories**
Focus on these 3-4 categories that work best:
- pressure washing
- power washing
- window cleaning
- gutter cleaning

### 4. **Single Page Per Pair**
Set `pages_per_pair=1` instead of 2
- Cuts requests in half
- Still gets most businesses (page 1 has the best ones)

---

## 🔧 Implementation Priority

If you want to try proxies, here's the quickest path:

1. **Sign up for Smartproxy** (has free trial)
2. **Get credentials** from their dashboard
3. **Add to .env**:
   ```
   PROXY_SERVER=http://proxy.smartproxy.com:port
   PROXY_USERNAME=your-username
   PROXY_PASSWORD=your-password
   USE_PROXY=true
   ```
4. **Update yp_client.py** (I can do this if you decide to go this route)

Let me know if you want to try any of these options!
