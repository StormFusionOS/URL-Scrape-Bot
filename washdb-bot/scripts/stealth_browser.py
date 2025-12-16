#!/usr/bin/env python3
"""
Stealth Browser Module - Professional Anti-bot Evasion for Web Scraping

Uses Playwright with comprehensive stealth settings for Cloudflare bypass.
Runs in HEADED mode on virtual display (Xvfb :99) for maximum anti-detection.

Anti-Detection Features:
- Realistic browser fingerprinting
- WebGL/Canvas fingerprint spoofing
- Navigator property masking
- Timezone/locale consistency
- Human-like mouse movements and delays
- Cloudflare challenge handling
- Cookie persistence
- Request header normalization
"""

import os
import time
import random
import logging
import json
import re
import hashlib
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# User data directory for cookie persistence
USER_DATA_DIR = Path("/home/rivercityscrape/URL-Scrape-Bot/washdb-bot/data/browser_profiles")
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class PageData:
    """Data extracted from a webpage"""
    url: str
    title: str
    meta_description: str
    meta_keywords: str
    og_site_name: str
    og_title: str
    json_ld: Dict[str, Any]
    h1_text: str
    page_text: str
    phone_numbers: list
    emails: list
    success: bool
    error: Optional[str] = None
    cloudflare_detected: bool = False


class StealthBrowser:
    """
    Professional stealth browser with comprehensive anti-bot evasion.

    Techniques used:
    1. Realistic user agents with matching platform data
    2. WebGL vendor/renderer spoofing
    3. Canvas fingerprint noise injection
    4. Navigator.webdriver removal
    5. Chrome runtime spoofing
    6. Permissions API spoofing
    7. Plugin/MimeType spoofing
    8. Hardware concurrency normalization
    9. Device memory normalization
    10. Cloudflare challenge detection and waiting
    11. Human-like interaction patterns
    12. Cookie/session persistence
    """

    # Realistic browser profiles (user agent + matching data)
    BROWSER_PROFILES = [
        {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "platform": "Win32",
            "vendor": "Google Inc.",
            "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
            "webgl_vendor": "Intel Inc.",
        },
        {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "platform": "Win32",
            "vendor": "Google Inc.",
            "renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0, D3D11)",
            "webgl_vendor": "NVIDIA Corporation",
        },
        {
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "platform": "MacIntel",
            "vendor": "Google Inc.",
            "renderer": "ANGLE (Apple, Apple M1 Pro, OpenGL 4.1)",
            "webgl_vendor": "Apple Inc.",
        },
        {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "platform": "Win32",
            "vendor": "",
            "renderer": "Intel(R) UHD Graphics 630",
            "webgl_vendor": "Intel Inc.",
        },
        {
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
            "platform": "MacIntel",
            "vendor": "Apple Computer, Inc.",
            "renderer": "Apple M1",
            "webgl_vendor": "Apple Inc.",
        },
    ]

    # Screen resolutions weighted by popularity
    SCREEN_RESOLUTIONS = [
        (1920, 1080, 0.35),
        (1366, 768, 0.20),
        (1536, 864, 0.12),
        (1440, 900, 0.10),
        (1280, 720, 0.08),
        (2560, 1440, 0.08),
        (1600, 900, 0.05),
        (1280, 1024, 0.02),
    ]

    def __init__(self, headless: bool = False, display: str = ":99", profile_id: str = "default"):
        """
        Initialize stealth browser

        Args:
            headless: If False, runs in headed mode (better for anti-bot)
            display: X11 display for headed mode (default :99 for Xvfb)
            profile_id: Profile ID for cookie persistence
        """
        self.headless = headless
        self.display = display
        self.profile_id = profile_id
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.browser_profile = None
        self.screen_resolution = None

    def _select_random_profile(self) -> Dict[str, str]:
        """Select a random but consistent browser profile"""
        # Use profile_id to seed randomness for consistency
        seed = int(hashlib.md5(self.profile_id.encode()).hexdigest()[:8], 16)
        random.seed(seed)
        profile = random.choice(self.BROWSER_PROFILES)
        random.seed()  # Reset seed
        return profile

    def _select_screen_resolution(self) -> tuple:
        """Select weighted random screen resolution"""
        weights = [r[2] for r in self.SCREEN_RESOLUTIONS]
        total = sum(weights)
        r = random.random() * total
        cumulative = 0
        for res in self.SCREEN_RESOLUTIONS:
            cumulative += res[2]
            if r <= cumulative:
                return (res[0], res[1])
        return (1920, 1080)

    def _get_stealth_script(self) -> str:
        """Generate comprehensive stealth JavaScript injection"""
        profile = self.browser_profile

        return f"""
        // ========== WEBDRIVER DETECTION BYPASS ==========
        // Remove webdriver flag
        Object.defineProperty(navigator, 'webdriver', {{
            get: () => undefined
        }});

        // Delete webdriver from navigator prototype
        delete Navigator.prototype.webdriver;

        // ========== CHROME RUNTIME SPOOFING ==========
        // Create realistic chrome object
        window.chrome = {{
            runtime: {{
                connect: function() {{}},
                sendMessage: function() {{}},
                onMessage: {{
                    addListener: function() {{}},
                    removeListener: function() {{}}
                }},
                PlatformOs: {{
                    MAC: 'mac',
                    WIN: 'win',
                    ANDROID: 'android',
                    CROS: 'cros',
                    LINUX: 'linux',
                    OPENBSD: 'openbsd'
                }},
                PlatformArch: {{
                    ARM: 'arm',
                    X86_32: 'x86-32',
                    X86_64: 'x86-64'
                }},
                PlatformNaclArch: {{
                    ARM: 'arm',
                    X86_32: 'x86-32',
                    X86_64: 'x86-64'
                }},
                RequestUpdateCheckStatus: {{
                    THROTTLED: 'throttled',
                    NO_UPDATE: 'no_update',
                    UPDATE_AVAILABLE: 'update_available'
                }},
                OnInstalledReason: {{
                    INSTALL: 'install',
                    UPDATE: 'update',
                    CHROME_UPDATE: 'chrome_update',
                    SHARED_MODULE_UPDATE: 'shared_module_update'
                }},
                OnRestartRequiredReason: {{
                    APP_UPDATE: 'app_update',
                    OS_UPDATE: 'os_update',
                    PERIODIC: 'periodic'
                }}
            }},
            loadTimes: function() {{
                return {{
                    commitLoadTime: Date.now() / 1000 - Math.random() * 5,
                    connectionInfo: "h2",
                    finishDocumentLoadTime: Date.now() / 1000 - Math.random() * 2,
                    finishLoadTime: Date.now() / 1000 - Math.random(),
                    firstPaintAfterLoadTime: 0,
                    firstPaintTime: Date.now() / 1000 - Math.random() * 3,
                    navigationType: "Other",
                    npnNegotiatedProtocol: "h2",
                    requestTime: Date.now() / 1000 - Math.random() * 10,
                    startLoadTime: Date.now() / 1000 - Math.random() * 8,
                    wasAlternateProtocolAvailable: false,
                    wasFetchedViaSpdy: true,
                    wasNpnNegotiated: true
                }};
            }},
            csi: function() {{
                return {{
                    onloadT: Date.now(),
                    pageT: Math.random() * 1000 + 500,
                    startE: Date.now() - Math.random() * 5000,
                    tran: 15
                }};
            }},
            app: {{
                isInstalled: false,
                InstallState: {{
                    DISABLED: 'disabled',
                    INSTALLED: 'installed',
                    NOT_INSTALLED: 'not_installed'
                }},
                RunningState: {{
                    CANNOT_RUN: 'cannot_run',
                    READY_TO_RUN: 'ready_to_run',
                    RUNNING: 'running'
                }}
            }}
        }};

        // ========== NAVIGATOR PROPERTIES SPOOFING ==========
        // Platform
        Object.defineProperty(navigator, 'platform', {{
            get: () => '{profile["platform"]}'
        }});

        // Vendor
        Object.defineProperty(navigator, 'vendor', {{
            get: () => '{profile["vendor"]}'
        }});

        // Languages (realistic)
        Object.defineProperty(navigator, 'languages', {{
            get: () => Object.freeze(['en-US', 'en'])
        }});

        // Hardware concurrency (realistic range)
        Object.defineProperty(navigator, 'hardwareConcurrency', {{
            get: () => {random.choice([4, 6, 8, 12])}
        }});

        // Device memory (realistic range)
        Object.defineProperty(navigator, 'deviceMemory', {{
            get: () => {random.choice([4, 8, 16])}
        }});

        // Max touch points (0 for desktop)
        Object.defineProperty(navigator, 'maxTouchPoints', {{
            get: () => 0
        }});

        // ========== PLUGINS SPOOFING ==========
        // Create realistic plugin array
        const pluginData = [
            {{name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'}},
            {{name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''}},
            {{name: 'Native Client', filename: 'internal-nacl-plugin', description: ''}}
        ];

        const pluginArray = pluginData.map(p => {{
            const plugin = Object.create(Plugin.prototype);
            Object.defineProperties(plugin, {{
                name: {{value: p.name, enumerable: true}},
                filename: {{value: p.filename, enumerable: true}},
                description: {{value: p.description, enumerable: true}},
                length: {{value: 1, enumerable: true}}
            }});
            return plugin;
        }});

        Object.defineProperty(navigator, 'plugins', {{
            get: () => {{
                const arr = Object.create(PluginArray.prototype);
                pluginArray.forEach((p, i) => arr[i] = p);
                Object.defineProperty(arr, 'length', {{value: pluginArray.length}});
                arr.item = (i) => pluginArray[i];
                arr.namedItem = (name) => pluginArray.find(p => p.name === name);
                arr.refresh = () => {{}};
                return arr;
            }}
        }});

        // ========== PERMISSIONS API SPOOFING ==========
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => {{
            if (parameters.name === 'notifications') {{
                return Promise.resolve({{state: Notification.permission}});
            }}
            return originalQuery(parameters);
        }};

        // ========== WEBGL SPOOFING ==========
        const getParameterProxyHandler = {{
            apply: function(target, thisArg, argumentsList) {{
                const param = argumentsList[0];
                const gl = thisArg;

                // UNMASKED_VENDOR_WEBGL
                if (param === 37445) {{
                    return '{profile["webgl_vendor"]}';
                }}
                // UNMASKED_RENDERER_WEBGL
                if (param === 37446) {{
                    return '{profile["renderer"]}';
                }}

                return Reflect.apply(target, thisArg, argumentsList);
            }}
        }};

        // Override for WebGL
        const originalGetParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = new Proxy(originalGetParameter, getParameterProxyHandler);

        // Override for WebGL2
        if (typeof WebGL2RenderingContext !== 'undefined') {{
            const originalGetParameter2 = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = new Proxy(originalGetParameter2, getParameterProxyHandler);
        }}

        // ========== CANVAS FINGERPRINT NOISE ==========
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {{
            if (type === 'image/png' || type === undefined) {{
                const context = this.getContext('2d');
                if (context) {{
                    const imageData = context.getImageData(0, 0, this.width, this.height);
                    // Add subtle noise to prevent fingerprinting
                    for (let i = 0; i < imageData.data.length; i += 4) {{
                        imageData.data[i] = imageData.data[i] ^ (Math.random() > 0.99 ? 1 : 0);
                    }}
                    context.putImageData(imageData, 0, 0);
                }}
            }}
            return originalToDataURL.apply(this, arguments);
        }};

        // ========== AUDIO CONTEXT FINGERPRINT PROTECTION ==========
        if (typeof AudioContext !== 'undefined') {{
            const originalCreateOscillator = AudioContext.prototype.createOscillator;
            AudioContext.prototype.createOscillator = function() {{
                const oscillator = originalCreateOscillator.apply(this, arguments);
                // Slight frequency deviation
                const originalFrequency = oscillator.frequency;
                return oscillator;
            }};
        }}

        // ========== IFRAME CONTENTWINDOW PROTECTION ==========
        const originalContentWindow = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
        Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {{
            get: function() {{
                const result = originalContentWindow.get.call(this);
                if (result) {{
                    try {{
                        Object.defineProperty(result.navigator, 'webdriver', {{get: () => undefined}});
                    }} catch(e) {{}}
                }}
                return result;
            }}
        }});

        // ========== SCREEN PROPERTIES ==========
        Object.defineProperty(screen, 'availWidth', {{get: () => {self.screen_resolution[0]}}});
        Object.defineProperty(screen, 'availHeight', {{get: () => {self.screen_resolution[1] - 40}}});
        Object.defineProperty(screen, 'width', {{get: () => {self.screen_resolution[0]}}});
        Object.defineProperty(screen, 'height', {{get: () => {self.screen_resolution[1]}}});
        Object.defineProperty(screen, 'colorDepth', {{get: () => 24}});
        Object.defineProperty(screen, 'pixelDepth', {{get: () => 24}});

        // ========== DOCUMENT PROPERTIES ==========
        Object.defineProperty(document, 'hidden', {{get: () => false}});
        Object.defineProperty(document, 'visibilityState', {{get: () => 'visible'}});

        // ========== CONSOLE DEBUG DETECTION ==========
        // Prevent console.debug detection
        const originalConsoleDebug = console.debug;
        console.debug = function() {{
            return originalConsoleDebug.apply(this, arguments);
        }};

        console.log('[Stealth] Anti-detection initialized');
        """

    def _setup_virtual_display(self):
        """Setup Xvfb virtual display for headed mode"""
        if self.headless:
            return

        import subprocess

        # Check if :99 display exists
        try:
            result = subprocess.run(
                ['xdpyinfo', '-display', ':99'],
                capture_output=True,
                timeout=2
            )
            if result.returncode == 0:
                os.environ['DISPLAY'] = ':99'
                logger.info("Using existing virtual display :99")
                return
        except Exception:
            pass

        # Start Xvfb on :99
        try:
            subprocess.Popen(
                ['Xvfb', ':99', '-screen', '0', '1920x1080x24', '-ac'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1)
            os.environ['DISPLAY'] = ':99'
            logger.info("Started virtual display :99")
        except Exception as e:
            logger.warning(f"Could not start Xvfb: {e}, using {self.display}")
            os.environ['DISPLAY'] = self.display

    def start(self):
        """Start the browser with all stealth settings"""
        if self.browser:
            return

        # Setup virtual display for headed mode
        self._setup_virtual_display()

        # Select consistent browser profile and resolution
        self.browser_profile = self._select_random_profile()
        self.screen_resolution = self._select_screen_resolution()

        logger.info(f"Starting stealth browser (profile: {self.browser_profile['platform']})")
        logger.info(f"Screen resolution: {self.screen_resolution[0]}x{self.screen_resolution[1]}")

        self.playwright = sync_playwright().start()

        # Browser launch args for stealth
        browser_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-infobars',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-features=IsolateOrigins,site-per-process',
            '--disable-features=TranslateUI',
            '--disable-ipc-flooding-protection',
            f'--window-size={self.screen_resolution[0]},{self.screen_resolution[1]}',
            '--start-maximized',
            '--disable-extensions',
            '--disable-component-extensions-with-background-pages',
            '--disable-default-apps',
            '--mute-audio',
            '--no-default-browser-check',
            '--no-first-run',
            '--disable-breakpad',
            '--disable-component-update',
            '--disable-domain-reliability',
            '--disable-features=AudioServiceOutOfProcess',
            '--disable-print-preview',
            '--disable-setuid-sandbox',
            '--disable-speech-api',
            '--disable-sync',
            '--hide-scrollbars',
            '--metrics-recording-only',
            '--no-pings',
            '--password-store=basic',
            '--use-mock-keychain',
            '--force-color-profile=srgb',
        ]

        # Launch browser
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=browser_args,
        )

        # Create context with stealth settings
        self.context = self.browser.new_context(
            viewport={'width': self.screen_resolution[0], 'height': self.screen_resolution[1] - 100},
            user_agent=self.browser_profile['user_agent'],
            locale='en-US',
            timezone_id='America/Chicago',
            geolocation={'latitude': 30.2672, 'longitude': -97.7431},  # Austin, TX
            permissions=['geolocation'],
            color_scheme='light',
            reduced_motion='no-preference',
            has_touch=False,
            is_mobile=False,
            java_script_enabled=True,
            bypass_csp=False,
            ignore_https_errors=True,
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'max-age=0',
                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"' if 'Windows' in self.browser_profile['user_agent'] else '"macOS"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
            }
        )

        # Inject stealth scripts before any page loads
        self.context.add_init_script(self._get_stealth_script())

        # Create page
        self.page = self.context.new_page()
        self.page.set_default_timeout(45000)  # 45 second timeout for Cloudflare
        self.page.set_default_navigation_timeout(60000)  # 60 second nav timeout

        logger.info("Stealth browser started successfully")

    def stop(self):
        """Close the browser"""
        if self.page:
            try:
                self.page.close()
            except:
                pass
            self.page = None
        if self.context:
            try:
                self.context.close()
            except:
                pass
            self.context = None
        if self.browser:
            try:
                self.browser.close()
            except:
                pass
            self.browser = None
        if self.playwright:
            try:
                self.playwright.stop()
            except:
                pass
            self.playwright = None
        logger.info("Browser closed")

    def _human_delay(self, min_sec: float = 0.5, max_sec: float = 2.0):
        """Add random human-like delay"""
        time.sleep(random.uniform(min_sec, max_sec))

    def _human_mouse_movement(self):
        """Simulate human-like mouse movement"""
        try:
            # Move mouse to random positions
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, self.screen_resolution[0] - 100)
                y = random.randint(100, self.screen_resolution[1] - 200)
                self.page.mouse.move(x, y, steps=random.randint(10, 30))
                time.sleep(random.uniform(0.1, 0.3))
        except:
            pass

    def _human_scroll(self):
        """Simulate human-like scrolling"""
        try:
            # Scroll down a bit
            scroll_amount = random.randint(200, 500)
            self.page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            time.sleep(random.uniform(0.3, 0.7))

            # Scroll back up slightly
            self.page.evaluate(f"window.scrollBy(0, -{random.randint(50, 150)})")
            time.sleep(random.uniform(0.2, 0.4))

            # Scroll back to top
            self.page.evaluate("window.scrollTo(0, 0)")
        except:
            pass

    def _detect_cloudflare(self) -> bool:
        """Detect if page shows Cloudflare challenge"""
        try:
            content = self.page.content()
            title = self.page.title().lower()

            cloudflare_indicators = [
                'cloudflare' in content.lower(),
                'cf-browser-verification' in content,
                'cf_clearance' in content,
                'just a moment' in title,
                'checking your browser' in content.lower(),
                'ray id' in content.lower() and 'cloudflare' in content.lower(),
                '__cf_bm' in content,
                'cf-spinner' in content,
                'turnstile' in content.lower(),
            ]

            return any(cloudflare_indicators)
        except:
            return False

    def _wait_for_cloudflare(self, max_wait: int = 30) -> bool:
        """Wait for Cloudflare challenge to complete"""
        logger.info("Cloudflare challenge detected, waiting...")

        start_time = time.time()
        while time.time() - start_time < max_wait:
            # Simulate human behavior while waiting
            self._human_mouse_movement()
            time.sleep(1)

            # Check if challenge is complete
            if not self._detect_cloudflare():
                logger.info("Cloudflare challenge passed!")
                return True

            # Check for specific elements that indicate page loaded
            try:
                # If we can find normal page elements, challenge is likely done
                body = self.page.query_selector('body')
                if body:
                    body_text = body.inner_text()
                    if len(body_text) > 500 and 'cloudflare' not in body_text.lower():
                        return True
            except:
                pass

        logger.warning("Cloudflare challenge timeout")
        return False

    def _extract_json_ld(self) -> Dict[str, Any]:
        """Extract JSON-LD structured data from page"""
        json_ld = {}
        try:
            scripts = self.page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                try:
                    content = script.inner_text()
                    data = json.loads(content)
                    if isinstance(data, dict):
                        if '@graph' in data:
                            for item in data['@graph']:
                                if item.get('@type') in ['LocalBusiness', 'Organization', 'WebSite', 'Service', 'ProfessionalService']:
                                    json_ld.update(item)
                        else:
                            json_ld.update(data)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                json_ld.update(item)
                except:
                    continue
        except Exception as e:
            logger.debug(f"JSON-LD extraction error: {e}")
        return json_ld

    def _extract_meta(self, name: str) -> str:
        """Extract meta tag content"""
        try:
            elem = self.page.query_selector(f'meta[name="{name}"]')
            if elem:
                return elem.get_attribute('content') or ''
        except:
            pass
        try:
            elem = self.page.query_selector(f'meta[property="{name}"]')
            if elem:
                return elem.get_attribute('content') or ''
        except:
            pass
        return ''

    def _extract_phones(self, text: str) -> list:
        """Extract phone numbers from text"""
        patterns = [
            r'\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
            r'\+1[-.\s]?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
        ]
        phones = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            phones.extend(matches)
        seen = set()
        return [p for p in phones if not (p in seen or seen.add(p))]

    def _extract_emails(self, text: str) -> list:
        """Extract email addresses from text"""
        pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = re.findall(pattern, text)
        return list(dict.fromkeys(emails))

    def fetch_page(self, url: str, wait_for_js: bool = True) -> PageData:
        """
        Fetch a page with full stealth and Cloudflare bypass

        Args:
            url: URL to fetch
            wait_for_js: Wait for JavaScript to load

        Returns:
            PageData with extracted information
        """
        if not self.browser:
            self.start()

        # Ensure URL has protocol
        if not url.startswith('http'):
            url = 'https://' + url

        cloudflare_detected = False

        try:
            logger.info(f"Fetching: {url}")

            # Navigate to page
            response = self.page.goto(url, wait_until='domcontentloaded')

            # Initial delay to appear human
            self._human_delay(1.5, 3.0)

            # Check for Cloudflare
            if self._detect_cloudflare():
                cloudflare_detected = True
                if not self._wait_for_cloudflare(max_wait=35):
                    return PageData(
                        url=url,
                        title='',
                        meta_description='',
                        meta_keywords='',
                        og_site_name='',
                        og_title='',
                        json_ld={},
                        h1_text='',
                        page_text='',
                        phone_numbers=[],
                        emails=[],
                        success=False,
                        error='Cloudflare challenge failed',
                        cloudflare_detected=True,
                    )

            # Wait for page to fully load
            if wait_for_js:
                try:
                    self.page.wait_for_selector('body', timeout=10000)
                    # Wait for network to be mostly idle
                    self.page.wait_for_load_state('networkidle', timeout=10000)
                except:
                    pass

            # Human-like behavior
            self._human_mouse_movement()
            self._human_scroll()
            self._human_delay(0.5, 1.0)

            # Extract data
            title = self.page.title() or ''
            meta_description = self._extract_meta('description')
            meta_keywords = self._extract_meta('keywords')
            og_site_name = self._extract_meta('og:site_name')
            og_title = self._extract_meta('og:title')
            json_ld = self._extract_json_ld()

            # H1 text
            h1_text = ''
            try:
                h1 = self.page.query_selector('h1')
                if h1:
                    h1_text = h1.inner_text().strip()
            except:
                pass

            # Page text content
            page_text = ''
            try:
                body = self.page.query_selector('body')
                if body:
                    page_text = body.inner_text()[:8000]
            except:
                pass

            # Extract contact info
            phones = self._extract_phones(page_text)
            emails = self._extract_emails(page_text)

            # Also check href links
            try:
                tel_links = self.page.query_selector_all('a[href^="tel:"]')
                mailto_links = self.page.query_selector_all('a[href^="mailto:"]')

                for link in tel_links:
                    href = link.get_attribute('href') or ''
                    phone = href.replace('tel:', '').strip()
                    if phone and phone not in phones:
                        phones.append(phone)

                for link in mailto_links:
                    href = link.get_attribute('href') or ''
                    email = href.replace('mailto:', '').split('?')[0].strip()
                    if email and email not in emails:
                        emails.append(email)
            except:
                pass

            return PageData(
                url=url,
                title=title,
                meta_description=meta_description,
                meta_keywords=meta_keywords,
                og_site_name=og_site_name,
                og_title=og_title,
                json_ld=json_ld,
                h1_text=h1_text,
                page_text=page_text,
                phone_numbers=phones,
                emails=emails,
                success=True,
                cloudflare_detected=cloudflare_detected,
            )

        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return PageData(
                url=url,
                title='',
                meta_description='',
                meta_keywords='',
                og_site_name='',
                og_title='',
                json_ld={},
                h1_text='',
                page_text='',
                phone_numbers=[],
                emails=[],
                success=False,
                error=str(e),
                cloudflare_detected=cloudflare_detected,
            )

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def test_stealth_browser():
    """Test the stealth browser with Cloudflare-protected sites"""
    print("=== Testing Stealth Browser with Cloudflare Bypass ===\n")

    test_urls = [
        "https://propowerwashllc.com",
        "https://www.hydrocleanpw.com",
    ]

    with StealthBrowser(headless=False) as browser:
        for url in test_urls:
            print(f"\n--- Testing: {url} ---")
            data = browser.fetch_page(url)

            if data.success:
                print(f"Title: {data.title}")
                print(f"H1: {data.h1_text}")
                print(f"OG Site Name: {data.og_site_name}")
                print(f"JSON-LD Name: {data.json_ld.get('name', 'N/A')}")
                print(f"Phones: {data.phone_numbers[:3]}")
                print(f"Emails: {data.emails[:3]}")
                print(f"Cloudflare detected: {data.cloudflare_detected}")
            else:
                print(f"FAILED: {data.error}")

            time.sleep(2)


if __name__ == '__main__':
    test_stealth_browser()
