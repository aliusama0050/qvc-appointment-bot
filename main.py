"""
QVC Slot Monitor Bot

Interactive CLI:
  1. Select city (Islamabad / Karachi)
  2. Select browser (Firefox / Chromium)
  3. Select mode (Monitor / Inspect)

When slot found: auto-clicks date -> Telegram alert -> you finish in browser.

Usage:
    python main.py             # Interactive CLI menu
    python main.py --inspect   # Skip menu, inspect mode
"""

import sys
import os
# Fix Windows console encoding for Unicode characters
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
import asyncio
import logging
import sys
import os

import config
from browser import launch_browser, navigate_to_qvc, wait_for_calendar, inspect_page, cleanup_browser, disconnect_browser
from calendar_monitor import monitor_calendar
from keepalive import session_keepalive, error_watcher
from telegram_bot import TelegramNotifier

logger = logging.getLogger("qvc.main")

CITIES = {
    "1": {"name": "Islamabad", "index": 0},
    "2": {"name": "Karachi",   "index": 1},
}

BROWSERS = {
    "1": {"name": "Chromium",  "type": "chromium"},
    "2": {"name": "Chromium", "type": "chromium"},
}


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header():
    clear_screen()
    print()
    print("  ╔══════════════════════════════════════════════════╗")
    print("  ║         QVC APPOINTMENT SLOT MONITOR             ║")
    print("  ║         Qatar Visa Center - Pakistan             ║")
    print("  ╚══════════════════════════════════════════════════╝")
    print()


def print_divider():
    print("  ──────────────────────────────────────────────────")


def select_city() -> dict:
    print_header()
    print("  Step 1: Select QVC Center")
    print_divider()
    print("  [1] Islamabad")
    print("  [2] Karachi")
    print_divider()

    while True:
        choice = input("  Enter choice (1 or 2): ").strip()
        if choice in CITIES:
            print(f"  -> {CITIES[choice]['name']}")
            return CITIES[choice]
        print("  Invalid. Enter 1 or 2.")


def select_browser() -> dict:
    # Chromium only — supports CDP so browser survives script exit
    print()
    print("  Browser: Chromium (stays open when bot stops)")
    return {"name": "Chromium", "type": "chromium"}


def enter_applicant_details() -> dict:
    """Collect applicant details via CLI. Uses .env values as defaults."""
    print()
    print("  Step 3: Applicant Details")
    print("  (Used for auto-recovery if session dies)")
    print_divider()

    # Passport
    default_pp = config.PASSPORT_NUMBER
    prompt = f"  Passport Number [{default_pp}]: " if default_pp else "  Passport Number: "
    pp = input(prompt).strip() or default_pp

    # VRN
    default_vrn = config.VISA_REF_NUMBER
    prompt = f"  Visa Ref Number [{default_vrn}]: " if default_vrn else "  Visa Ref Number: "
    vrn = input(prompt).strip() or default_vrn

    # Mobile
    default_mob = config.MOBILE_NUMBER
    prompt = f"  Mobile Number [{default_mob}]: " if default_mob else "  Mobile Number: "
    mob = input(prompt).strip() or default_mob

    # Email
    default_email = config.EMAIL_ADDRESS
    prompt = f"  Email Address [{default_email}]: " if default_email else "  Email Address: "
    email = input(prompt).strip() or default_email

    details = {
        "passport": pp,
        "vrn": vrn,
        "mobile": mob,
        "email": email,
    }

    # Store in config so auto_login can access them
    config.PASSPORT_NUMBER = pp
    config.VISA_REF_NUMBER = vrn
    config.MOBILE_NUMBER = mob
    config.EMAIL_ADDRESS = email

    print_divider()
    print(f"  Passport: {pp}")
    print(f"  VRN:      {vrn}")
    print(f"  Mobile:   {mob or '(not set)'}")
    print(f"  Email:    {email or '(not set)'}")

    return details


def select_mode() -> str:
    print()
    print("  Step 4: Select Mode")
    print_divider()
    print("  [1] Monitor  — Watch for slots, click date, notify Telegram")
    print("  [2] Inspect  — Dump page DOM for selector discovery")
    print_divider()

    while True:
        choice = input("  Enter choice (1 or 2): ").strip()
        if choice == "1":
            return "monitor"
        elif choice == "2":
            return "inspect"
        print("  Invalid. Enter 1 or 2.")


def confirm_settings(city: dict, browser: dict, applicant: dict, mode: str) -> bool:
    print()
    print("  ╔══════════════════════════════════════════════════╗")
    print("  ║                  LAUNCH SETTINGS                 ║")
    print("  ╠══════════════════════════════════════════════════╣")
    print(f"  ║  City:     {city['name']:<39}║")
    print(f"  ║  Browser:  {browser['name']:<39}║")
    print(f"  ║  Mode:     {mode.title():<39}║")
    print(f"  ║  Passport: {applicant['passport']:<39}║")
    print(f"  ║  VRN:      {applicant['vrn']:<39}║")
    mob = applicant['mobile'] or '(not set)'
    email = applicant['email'] or '(not set)'
    print(f"  ║  Mobile:   {mob:<39}║")
    print(f"  ║  Email:    {email:<39}║")
    tg = 'Configured' if config.TELEGRAM_BOT_TOKEN else 'NOT SET'
    print(f"  ║  Telegram: {tg:<39}║")
    proxy = config.PROXY_URL or 'Direct (no proxy)'
    print(f"  ║  Proxy:    {proxy:<39}║")
    print(f"  ║  Poll:     {str(config.POLL_INTERVAL) + 's':<39}║")
    print("  ╚══════════════════════════════════════════════════╝")

    choice = input("\n  Start bot? (y/n): ").strip().lower()
    return choice in ("y", "yes", "")


def setup_logging():
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.SCREENSHOT_DIR / "bot.log", encoding="utf-8"),
        ],
    )


def parse_args():
    parser = argparse.ArgumentParser(description="QVC Slot Monitor Bot")
    parser.add_argument("--inspect", action="store_true", help="Inspect mode")
    parser.add_argument("--city", choices=["islamabad", "karachi"])
    parser.add_argument("--browser", choices=["chromium"], default="chromium")
    return parser.parse_args()


async def run_inspect_mode(city: dict, browser_type: str):
    logger.info(f"=== INSPECT MODE ({city['name']}, {browser_type}) ===")

    pw, context, page = await launch_browser(browser_type)
    try:
        await navigate_to_qvc(page)
        await asyncio.to_thread(input, "Press ENTER once you've reached the calendar page...")
        summary_path = await inspect_page(page)
        logger.info(f"Done! Check dom_dump.html and {summary_path}")
        await asyncio.to_thread(input, "Press ENTER to close the browser...")
    finally:
        await cleanup_browser(pw, context)


async def check_session_alive(page) -> bool:
    """Check if we're still on the calendar page. More tolerant — checks URL too."""
    try:
        # URL check first (most reliable — doesn't depend on DOM state)
        if "slotdetails" in page.url:
            return True
        # DOM check as backup
        calendar = await page.query_selector("sb-datepicker")
        if calendar:
            return True
        # Also check if we're on schedule page (might be between renders)
        if "schedule" in page.url:
            return True
        return False
    except Exception:
        return False


async def perform_login(page, telegram, city) -> bool:
    """
    Fully automated login: root page → language → country → form → CAPTCHA → calendar.
    Only user action: reply to CAPTCHA on Telegram.
    Returns True if calendar page was reached.
    """
    from auto_login import auto_fill_and_submit
    success = await auto_fill_and_submit(page, telegram, city)
    return success


async def run_bot(city: dict, browser_type: str):
    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        sys.exit(1)
    if not config.TELEGRAM_CHAT_ID or config.TELEGRAM_CHAT_ID == 0:
        logger.error("TELEGRAM_CHAT_ID not set!")
        sys.exit(1)

    telegram = TelegramNotifier()
    await telegram.start()

    from keepalive import set_telegram
    set_telegram(telegram)

    pw = None
    context = None

    try:
        print(f"\n  Launching {browser_type.title()} for {city['name']}...")
        pw, context, page = await launch_browser(browser_type)

        await telegram.send_message(
            f"QVC Bot starting...\n"
            f"City: {city['name']} | Browser: {browser_type.title()}\n"
            f"Logging in automatically.\n"
            f"You only need to reply with CAPTCHA text when asked."
        )

        # === MAIN LOOP: AUTO-LOGIN + MONITOR + AUTO-RECOVERY ===
        session_count = 0
        skip_login = False
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 10  # Exit after 10 consecutive failures

        while consecutive_failures < MAX_CONSECUTIVE_FAILURES:
            session_count += 1

            if skip_login:
                # Recovery already got us to the calendar — skip login
                logger.info(f"Session #{session_count}: Recovered — skipping login")
                skip_login = False
            else:
                # --- AUTO-LOGIN ---
                logger.info(f"Session #{session_count}: Performing auto-login...")
                login_success = await perform_login(page, telegram, city)

                if not login_success:
                    await telegram.send_message(
                        f"Auto-login failed ({city['name']}).\n"
                        "Complete login manually in the browser.\n"
                        "Bot will resume when calendar appears."
                    )
                    await wait_for_calendar(page)

            # --- CALENDAR REACHED — START MONITORING ---
            consecutive_failures = 0  # Reset on successful calendar reach

            await telegram.send_message(
                f"Session #{session_count}: Monitoring {city['name']}...\n"
                f"Poll: {config.POLL_INTERVAL}s | Keepalive: {config.KEEPALIVE_INTERVAL}s\n\n"
                f"Slot found → auto-clicks date → Telegram alert\n"
                f"You select time + CAPTCHA #2 in browser"
            )

            stop_event = asyncio.Event()
            keepalive_task = asyncio.create_task(session_keepalive(page, stop_event))
            error_task = asyncio.create_task(error_watcher(page, stop_event))

            try:
                await monitor_with_recovery(page, stop_event, telegram, city)
            finally:
                stop_event.set()
                await asyncio.gather(keepalive_task, error_task, return_exceptions=True)

            # --- SESSION LOST → SMART RECOVERY ---
            consecutive_failures += 1
            logger.warning(f"Session lost! ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}) Starting recovery...")
            recovered = await smart_recovery(page, telegram, city)

            if recovered:
                skip_login = True
                consecutive_failures = 0  # Reset on successful recovery

        # Exited while loop — too many failures
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.error(f"Too many consecutive failures ({MAX_CONSECUTIVE_FAILURES}). Stopping.")
            await telegram.send_message(
                f"Bot stopping — {MAX_CONSECUTIVE_FAILURES} consecutive failures.\n"
                "Restart manually: python main.py"
            )

    finally:
        await telegram.stop()
        # Disconnect Playwright — browser stays open (Chromium CDP)
        await disconnect_browser(pw)
        logger.info("Bot stopped. Browser stays open — close it manually when done.")


async def smart_recovery(page, telegram, city) -> bool:
    """
    Recovery when session/page is lost.
    QVC always invalidates the session server-side on errors,
    so intermediate steps (navigate to /slotdetails) never work.
    Always go straight to full re-login from root.

    Recovery chain:
      Step 1: Dismiss error modals (quick check — maybe it's just a popup)
      Step 2: Full auto-login from root (the only reliable recovery)
      Step 3: Manual fallback (if auto-login fails)
    """
    import dom_selectors as sel
    from browser import query_first

    await telegram.send_message(
        f"Session lost ({city['name']}). Starting recovery..."
    )

    # Step 1: Quick check — dismiss modals, maybe calendar is still alive
    logger.info("Recovery Step 1: Dismiss error modals...")
    try:
        for _ in range(3):
            modal = await query_first(page, sel.ERROR_MODAL)
            if modal:
                btn = await query_first(page, sel.ERROR_DISMISS_BUTTON)
                if btn:
                    await btn.click()
                    await asyncio.sleep(0.5)
                else:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.5)
            else:
                break

        await asyncio.sleep(2)
        calendar = await page.query_selector("sb-datepicker")
        if calendar:
            logger.info("Recovery Step 1 SUCCESS: Calendar still alive after dismissing modals!")
            await telegram.send_message("Recovered! Resuming monitoring.")
            return True
    except Exception as e:
        logger.debug(f"Step 1 error: {e}")

    # Step 2: Full auto-login from root (always navigate to root — no shortcuts)
    if config.PASSPORT_NUMBER and config.VISA_REF_NUMBER:
        logger.info("Recovery Step 2: Full re-login from root...")
        await telegram.send_message(
            "Session dead. Re-logging in from scratch...\n"
            "Reply with CAPTCHA when asked."
        )
        from auto_login import auto_fill_and_submit

        success = await auto_fill_and_submit(page, telegram, city)
        if success:
            logger.info("Recovery Step 2 SUCCESS: Re-login complete!")
            return True

    # Step 3: Manual fallback
    logger.warning("Recovery Step 3: Manual re-login required.")
    await telegram.send_message(
        f"Auto-recovery failed ({city['name']}).\n\n"
        f"Re-login manually in the browser:\n"
        f"1. Select Pakistan\n"
        f"2. Book Appointment\n"
        f"3. Passport + VRN + CAPTCHA\n"
        f"4. Submit\n\n"
        f"Bot resumes when calendar appears."
    )

    try:
        await page.goto(
            "https://www.qatarvisacenter.com",
            wait_until="domcontentloaded",
            timeout=30000
        )
    except Exception as e:
        logger.error(f"Navigation failed: {e}")

    return False


async def monitor_with_recovery(page, stop_event, telegram, city):
    consecutive_missing = 0
    MAX_MISSING = 20  # ~60 seconds (check every 3s)

    monitor_task = asyncio.create_task(
        monitor_calendar(page, stop_event, telegram, city)
    )

    try:
        while not stop_event.is_set():
            await asyncio.sleep(3)

            if monitor_task.done():
                # Propagate any exception from the monitor task
                if not monitor_task.cancelled():
                    exc = monitor_task.exception() if not monitor_task.cancelled() else None
                    if exc:
                        logger.error(f"Monitor crashed: {exc}")
                break

            if await check_session_alive(page):
                consecutive_missing = 0
            else:
                consecutive_missing += 1
                logger.warning(f"Calendar missing ({consecutive_missing}/{MAX_MISSING})")

                if consecutive_missing >= MAX_MISSING:
                    logger.error("Session dead")
                    stop_event.set()
                    break
    finally:
        if not monitor_task.done():
            stop_event.set()
            try:
                await asyncio.wait_for(monitor_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                monitor_task.cancel()


async def main():
    args = parse_args()

    if args.inspect:
        city = CITIES["1"]
        if args.city == "karachi":
            city = CITIES["2"]
        browser_type = args.browser or "chromium"
        await run_inspect_mode(city, browser_type)
        return

    # --- Interactive CLI ---
    city = select_city()
    browser = select_browser()
    applicant = enter_applicant_details()
    mode = select_mode()

    if not confirm_settings(city, browser, applicant, mode):
        print("\n  Cancelled.")
        return

    print()

    if mode == "inspect":
        await run_inspect_mode(city, browser["type"])
    else:
        await run_bot(city, browser["type"])


if __name__ == "__main__":
    setup_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n  Bot stopped. Goodbye!")
