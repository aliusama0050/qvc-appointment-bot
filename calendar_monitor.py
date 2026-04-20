"""
QVC Slot Monitor - Calendar Monitoring
Polls calendar across 3 months. When slot found:
  1. Auto-clicks the available date
  2. Sends Telegram alert + screenshot
  3. User selects time + solves CAPTCHA manually in browser
  4. Keeps monitoring for more slots
"""

import asyncio
import sys
import time
import logging
from datetime import datetime
from playwright.async_api import Page

import config
import dom_selectors as sel
from browser import query_first, query_all, get_page_lock
from keepalive import burst
from telegram_bot import TelegramNotifier

logger = logging.getLogger("qvc.calendar")

SPINNER = [".", "..", "...", "....", ".....", "......"]


def print_status(poll_count: int, months_str: str,
                 interval: float, errors: int, elapsed: float):
    """Print a live status line to the console."""
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60
    mode = "BURST" if burst.is_burst else "NORMAL"
    spin = SPINNER[poll_count % len(SPINNER)]

    status = (
        f"\r  [{mode}] Poll #{poll_count} | "
        f"{months_str} | "
        f"{interval}s | "
        f"Err:{errors} | "
        f"{mins:02d}:{secs:02d} | "
        f"Scanning{spin}     "
    )
    sys.stdout.write(status)
    sys.stdout.flush()


def print_banner():
    """Print the monitoring banner."""
    print("\n" + "=" * 60)
    print("  QVC SLOT MONITOR — DETECT + CLICK DATE + NOTIFY")
    print("=" * 60)
    print("  Checking 3 months every poll cycle")
    print("  Slot found -> auto-clicks date -> Telegram alert")
    print("  You select time + solve CAPTCHA in browser")
    print("=" * 60)


async def refresh_calendar_data(page: Page, city_index: int = 0):
    """
    Force Angular to re-fetch calendar data by re-clicking the city dropdown.
    city_index: 0 = Islamabad, 1 = Karachi
    """
    try:
        dropdown_btn = await page.query_selector("button[name='selectedVsc']")
        if not dropdown_btn:
            await _refresh_fallback(page)
            return

        await dropdown_btn.click()
        await asyncio.sleep(0.3)

        nth = city_index + 1
        city_option = await page.query_selector(
            f".dropdown-menu.show li:nth-child({nth}) a"
        )
        if not city_option:
            city_option = await page.query_selector(
                f".dropdown-menu li:nth-child({nth}) a"
            )

        if city_option:
            await city_option.click()
            await asyncio.sleep(0.8)
            logger.debug("Calendar data refreshed via VCS re-selection")
        else:
            await page.keyboard.press("Escape")
            await _refresh_fallback(page)

    except Exception as e:
        logger.debug(f"Calendar refresh error (non-fatal): {e}")
        try:
            await _refresh_fallback(page)
        except Exception:
            pass


async def _refresh_fallback(page: Page):
    """Fallback: re-click Normal radio button."""
    radio = await page.query_selector(
        "input[type='radio'][name='appointmentType'][value='Normal']"
    )
    if radio:
        await radio.click()
        await asyncio.sleep(0.8)


async def check_month_for_slots(page: Page) -> list:
    """Check currently displayed month for available date cells."""
    available, selector = await query_all(page, sel.AVAILABLE_DATE)
    if available:
        logger.info(f"Found {len(available)} available date(s) using: {selector}")
    return available


async def navigate_next_month(page: Page) -> bool:
    """Click next-month arrow. Returns True if successful."""
    btn = await query_first(page, sel.NEXT_MONTH_BUTTON)
    if btn:
        if await btn.get_attribute("disabled") is not None:
            return False
        await btn.click()
        await asyncio.sleep(0.5)
        return True
    return False


async def navigate_prev_month(page: Page) -> bool:
    """Click prev-month arrow. Returns True if successful."""
    btn = await query_first(page, sel.PREV_MONTH_BUTTON)
    if btn:
        if await btn.get_attribute("disabled") is not None:
            return False
        await btn.click()
        await asyncio.sleep(0.5)
        return True
    return False


async def get_current_month_label(page: Page) -> str:
    """Get the month/year label from the calendar."""
    el = await query_first(page, sel.MONTH_YEAR_LABEL)
    if el:
        return (await el.text_content() or "").strip()
    return "unknown"


async def get_available_date_texts(page: Page, elements: list) -> list[str]:
    """Extract date numbers from available date elements."""
    dates = []
    for el in elements:
        try:
            text = await el.text_content()
            if text:
                dates.append(text.strip())
        except Exception:
            pass
    return dates


async def click_available_date(page: Page) -> str | None:
    """
    Re-query and click the first available date.
    Returns the date text if clicked, None if failed.
    """
    available, _ = await query_all(page, sel.AVAILABLE_DATE)
    if not available:
        return None

    try:
        date_text = (await available[0].text_content() or "").strip()
        await available[0].click()
        logger.info(f"Clicked available date: {date_text}")
        return date_text
    except Exception as e:
        logger.error(f"Failed to click date: {e}")
        return None


async def monitor_calendar(page: Page, stop_event: asyncio.Event,
                           telegram: TelegramNotifier = None,
                           city: dict = None) -> bool:
    """
    Main calendar monitoring loop.
    When slot found:
      1. Auto-clicks the available date
      2. Sends Telegram alert with screenshot
      3. User handles time selection + CAPTCHA in browser
      4. Keeps monitoring (doesn't stop after finding a slot)
    """
    city_name = city["name"] if city else "Unknown"
    city_index = city["index"] if city else 0

    print_banner()
    print(f"  City: {city_name}")
    print()
    logger.info(f"Monitoring {city_name} (polling every {config.POLL_INTERVAL}s)")

    poll_count = 0
    start_time = time.monotonic()
    error_count = 0
    last_status_time = time.monotonic()
    last_alert_time = 0.0  # Min 30s between alerts to prevent spam
    last_refresh_time = 0.0  # Track when we last refreshed data from server
    REFRESH_INTERVAL = 30  # Only re-click dropdown every 30s to avoid killing session

    while not stop_event.is_set():
        try:
            interval = burst.poll_interval
            poll_count += 1

            async with get_page_lock():
                # --- Refresh data from server (only every 30s) ---
                # Re-clicking the dropdown too often causes "Connection to server lost"
                now = time.monotonic()
                if now - last_refresh_time >= REFRESH_INTERVAL:
                    await refresh_calendar_data(page, city_index)
                    last_refresh_time = now

                # --- Check months ---
                # Full 3-month scan only during refresh cycles (every 30s)
                # Between refreshes, just read the currently visible month (no clicks)
                did_refresh = (now - last_refresh_time < 2)  # True if we just refreshed
                months_to_check = 3 if did_refresh else 1
                months_forward = 0
                months_checked = []

                for month_idx in range(months_to_check):
                    month_label = await get_current_month_label(page)
                    months_checked.append(month_label)
                    available = await check_month_for_slots(page)

                    if available and (time.monotonic() - last_alert_time) > 30:
                        date_texts = await get_available_date_texts(page, available)
                        elapsed = time.monotonic() - start_time

                        # --- AUTO-CLICK THE DATE ---
                        clicked_date = await click_available_date(page)

                        # Console alert
                        now = datetime.now().strftime("%H:%M:%S")
                        print(f"\n\n  {'='*50}")
                        print(f"  [{now}] SLOT AVAILABLE! ({city_name})")
                        print(f"  Month: {month_label}")
                        print(f"  Dates: {', '.join(date_texts)}")
                        if clicked_date:
                            print(f"  CLICKED: {clicked_date}")
                            print(f"  Now select TIME SLOT in the browser!")
                        else:
                            print(f"  Could not auto-click (may have been taken)")
                        print(f"  Found after {poll_count} polls ({int(elapsed)}s)")
                        print(f"  {'='*50}\n")
                        logger.info(f"SLOT in {month_label}! Dates: {date_texts}, Clicked: {clicked_date}")

                        # --- SCREENSHOT AFTER CLICKING ---
                        await asyncio.sleep(0.5)  # Let time slots load

                        # Telegram notification
                        if telegram:
                            if clicked_date:
                                await telegram.send_message(
                                    f"SLOT FOUND & DATE CLICKED!\n"
                                    f"City: {city_name}\n"
                                    f"Month: {month_label}\n"
                                    f"Clicked date: {clicked_date}\n"
                                    f"Available dates: {', '.join(date_texts)}\n\n"
                                    f"NOW in the browser:\n"
                                    f"1. Select a time slot\n"
                                    f"2. Click Next\n"
                                    f"3. Solve CAPTCHA #2\n"
                                    f"4. Confirm booking"
                                )
                            else:
                                await telegram.send_message(
                                    f"SLOT AVAILABLE (could not auto-click)!\n"
                                    f"City: {city_name}\n"
                                    f"Month: {month_label}\n"
                                    f"Dates: {', '.join(date_texts)}\n\n"
                                    f"Click the date manually in the browser!"
                                )

                            screenshot_path = config.SCREENSHOT_DIR / f"slot_{datetime.now().strftime('%H%M%S')}.png"
                            await page.screenshot(path=str(screenshot_path))
                            await telegram.send_photo(
                                screenshot_path,
                                caption=f"{'Date clicked!' if clicked_date else 'Slot available!'} — {city_name} {month_label}"
                            )

                        last_alert_time = time.monotonic()

                        # STOP navigating after clicking a date — user needs to see time slots
                        if clicked_date:
                            break

                    # Navigate to next month (unless last)
                    if month_idx < 2:
                        if await navigate_next_month(page):
                            months_forward += 1
                        else:
                            break

                # Navigate back to first month
                for _ in range(months_forward):
                    await navigate_prev_month(page)

            # Live console status
            elapsed = time.monotonic() - start_time
            checked_str = " + ".join(months_checked) if months_checked else "?"
            print_status(poll_count, checked_str, interval, error_count, elapsed)

            # Periodic Telegram status (every 5 min)
            if telegram and (time.monotonic() - last_status_time) >= 300:
                mins = int(elapsed) // 60
                mode = "BURST" if burst.is_burst else "Normal"
                await telegram.send_message(
                    f"Still monitoring ({city_name})...\n"
                    f"Polls: {poll_count} | Mode: {mode}\n"
                    f"Checking: {checked_str}\n"
                    f"Uptime: {mins} min | Errors: {error_count}"
                )
                last_status_time = time.monotonic()

            await asyncio.sleep(interval)

        except Exception as e:
            error_count += 1
            logger.error(f"Calendar monitor error: {e}")
            burst.record_error()

            if telegram and error_count % 5 == 0:
                await telegram.send_message(
                    f"Warning: {error_count} errors ({city_name}).\n"
                    f"Latest: {type(e).__name__}: {str(e)[:100]}"
                )

            # Recover navigation
            try:
                async with get_page_lock():
                    for _ in range(2):
                        prev = await query_first(page, sel.PREV_MONTH_BUTTON)
                        if prev and await prev.get_attribute("disabled") is None:
                            await prev.click()
                            await asyncio.sleep(0.3)
            except Exception:
                pass
            await asyncio.sleep(1)

    return False
