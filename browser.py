"""
QVC Appointment Booking Bot - Browser Management
Launches Chromium/Firefox via Playwright (visible, headed).
Chromium uses CDP connect — browser survives script exit.
"""

import asyncio
import logging
import subprocess
import time
from pathlib import Path
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page

import config
import dom_selectors as sel

logger = logging.getLogger("qvc.browser")

PROFILE_DIR = Path(__file__).parent / ".browser_profile"
CDP_PORT = 9222  # Chrome DevTools Protocol port for Chromium

# Shared lock for page access — lazy init to avoid event loop binding issues
_page_lock: asyncio.Lock | None = None


def get_page_lock() -> asyncio.Lock:
    """Get or create the page lock. Must be called from within a running event loop."""
    global _page_lock
    if _page_lock is None:
        _page_lock = asyncio.Lock()
    return _page_lock

_playwright_instance: Playwright | None = None


async def query_first(page: Page, selector_list: list[str]):
    """Instantly query for the first matching element (no waiting)."""
    for selector in selector_list:
        try:
            el = await page.query_selector(selector)
            if el:
                return el
        except Exception:
            continue
    return None


async def query_all(page: Page, selector_list: list[str]):
    """Instantly query all matching elements using the first selector that hits."""
    for selector in selector_list:
        try:
            elements = await page.query_selector_all(selector)
            if elements:
                return elements, selector
        except Exception:
            continue
    return [], None


async def wait_for_first(page: Page, selector_list: list[str], timeout: int = 5000):
    """Wait for the first matching element from a selector list."""
    for selector in selector_list:
        try:
            el = await page.wait_for_selector(selector, timeout=timeout, state="attached")
            if el:
                return el
        except Exception:
            continue
    return None


async def try_selector(page: Page, selector_list: list[str]) -> str | None:
    """Try each selector instantly, return the first one that matches."""
    for selector in selector_list:
        try:
            el = await page.query_selector(selector)
            if el:
                return selector
        except Exception:
            continue
    return None


async def _find_chromium_path() -> str:
    """Find Chromium/Chrome executable path."""
    import shutil
    # Playwright's bundled chromium
    pw = await async_playwright().start()
    path = pw.chromium.executable_path
    await pw.stop()
    if path and Path(path).exists():
        return path
    # System Chrome
    for name in ["chrome", "chromium", "google-chrome"]:
        found = shutil.which(name)
        if found:
            return found
    # Windows default paths
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]:
        if Path(p).exists():
            return p
    return ""


async def launch_browser(browser_type: str = "chromium") -> tuple[Playwright, BrowserContext, Page]:
    """
    Launch browser that SURVIVES script exit.

    Chromium: launched as independent subprocess with CDP debugging port.
              Playwright connects via CDP. When script exits, browser stays open.

    Firefox:  uses Playwright persistent context (will close on script exit).
              Chromium is recommended.
    """
    global _playwright_instance
    profile_dir = PROFILE_DIR / browser_type
    profile_dir.mkdir(parents=True, exist_ok=True)

    pw = await async_playwright().start()
    _playwright_instance = pw

    if browser_type == "chromium":
        # Launch Chromium as a SEPARATE process — not managed by Playwright
        # This means the browser survives when the Python script exits
        chrome_path = await _find_chromium_path()
        if not chrome_path:
            logger.error("Chromium not found! Run: playwright install chromium")
            raise RuntimeError("Chromium executable not found")

        # Check if already running on CDP port
        browser = None
        try:
            browser = await pw.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
            logger.info(f"Connected to existing Chromium on port {CDP_PORT}")
        except Exception:
            # Not running — launch it as a subprocess
            logger.info(f"Launching Chromium as independent process...")
            cmd = [
                chrome_path,
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={str(profile_dir)}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ]
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Wait for CDP to be ready
            for attempt in range(15):
                try:
                    await asyncio.sleep(1)
                    browser = await pw.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
                    logger.info(f"Connected to Chromium via CDP (attempt {attempt + 1})")
                    break
                except Exception:
                    continue

            if not browser:
                raise RuntimeError(f"Could not connect to Chromium on port {CDP_PORT}")

        # Get or create a page
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        if context.pages:
            page = context.pages[0]
        else:
            page = await context.new_page()

    else:
        raise RuntimeError(f"Unsupported browser: {browser_type}. Use 'chromium'.")

    # Anti-detection
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    logger.info(f"{browser_type.title()} launched (visible mode, anti-detection)")
    return pw, context, page


async def navigate_to_qvc(page: Page):
    """Navigate to the QVC website root (country selection page)."""
    base_url = config.QVC_URL.rstrip("/").rsplit("/home", 1)[0]
    logger.info(f"Navigating to {base_url}")
    await page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
    logger.info("QVC page loaded — select Pakistan in the browser")


async def wait_for_calendar(page: Page, timeout: int = 600) -> str:
    """
    Wait for the calendar page to appear (signals login complete).
    Timeout after 10 minutes by default. Logs reminder every 60s.
    """
    logger.info("Waiting for calendar page...")
    start = asyncio.get_running_loop().time()
    last_reminder = start

    while True:
        matched = await try_selector(page, sel.CALENDAR_CONTAINER)
        if matched:
            logger.info(f"Calendar detected! Selector: {matched}")
            return matched

        now = asyncio.get_running_loop().time()
        elapsed = now - start

        # Timeout
        if elapsed > timeout:
            logger.warning(f"Calendar wait timed out after {timeout}s")
            return ""

        # Reminder every 60 seconds
        if now - last_reminder > 60:
            mins = int(elapsed) // 60
            logger.info(f"Still waiting for calendar... ({mins} min elapsed)")
            last_reminder = now

        await asyncio.sleep(1)


async def disconnect_browser(pw: Playwright | None):
    """Disconnect Playwright from browser WITHOUT closing it.
    For Chromium CDP: browser stays open as an independent process.
    For Firefox: browser will close (Playwright owns it)."""
    global _playwright_instance
    try:
        if pw:
            await pw.stop()
    except Exception:
        pass
    _playwright_instance = None


async def cleanup_browser(pw: Playwright | None, context: BrowserContext | None):
    """Full cleanup — closes everything. Only used in inspect mode."""
    global _playwright_instance
    try:
        if context:
            await context.close()
    except Exception:
        pass
    try:
        if pw:
            await pw.stop()
    except Exception:
        pass
    _playwright_instance = None


async def inspect_page(page: Page) -> str:
    """Dump the current page DOM for selector discovery."""
    dump_path = Path(__file__).parent / "dom_dump.html"
    html = await page.content()
    dump_path.write_text(html, encoding="utf-8")

    summary = await page.evaluate("""() => {
        const elements = [];
        const interesting = document.querySelectorAll(
            'table, .calendar, [class*="calendar"], [class*="date"], ' +
            '[class*="slot"], [class*="time"], [class*="captcha"], ' +
            '[class*="modal"], [class*="error"], [class*="btn"], ' +
            'button, input[type="submit"], select, ' +
            'td[class], td[data-handler], .ui-datepicker, ' +
            '[id*="calendar"], [id*="Calendar"], [id*="date"], [id*="Date"]'
        );
        interesting.forEach(el => {
            elements.push({
                tag: el.tagName.toLowerCase(),
                id: el.id || null,
                classes: el.className || null,
                name: el.getAttribute('name'),
                type: el.getAttribute('type'),
                text: el.textContent?.trim().substring(0, 80) || null,
                src: el.getAttribute('src'),
                selector: el.id ? '#' + el.id : (el.className ? '.' + el.className.split(' ').join('.') : el.tagName.toLowerCase())
            });
        });
        return elements;
    }""")

    summary_path = Path(__file__).parent / "dom_summary.txt"
    lines = ["=== QVC Page Interactive Elements ===\n"]
    for el in summary:
        lines.append(f"Tag: {el['tag']}")
        if el.get("id"):
            lines.append(f"  ID: #{el['id']}")
        if el.get("classes"):
            lines.append(f"  Classes: {el['classes']}")
        if el.get("name"):
            lines.append(f"  Name: {el['name']}")
        if el.get("text"):
            lines.append(f"  Text: {el['text'][:80]}")
        lines.append(f"  Suggested: {el['selector']}")
        lines.append("")

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"DOM dump: {dump_path}")
    logger.info(f"Summary: {summary_path}")
    return str(summary_path)
