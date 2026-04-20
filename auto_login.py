"""
QVC Slot Monitor - Auto Login & Form Fill
Automates the entire flow from root URL to calendar page:
  1. Navigate to root /
  2. Select "Pakistan - English" country
  3. Click "Book Appointment"
  4. Auto-fill passport, VRN, contact details
  5. CAPTCHA #1 via Telegram (screenshot + reply)
  6. Submit form
  7. Wait for calendar page

Used for session recovery so you only need to reply with CAPTCHA text on Telegram.
"""

import asyncio
import logging
from datetime import datetime
from playwright.async_api import Page

import config
from telegram_bot import TelegramNotifier

logger = logging.getLogger("qvc.autologin")

# =============================================================================
# SELECTORS — Root page (language + country selection)
# =============================================================================
# Root page structure:
#   <div class="bghome">
#     <input placeholder="-- Select Language --" data-bs-toggle="dropdown">
#     <ul class="dropdown-menu">
#       <li><a>English</a><a>عربى</a>...</li>
#     </ul>
#   </div>
# After language: country dropdown appears, then submit/continue

SEL_LANGUAGE_INPUT = ".bghome input[placeholder*='Language']"
SEL_LANGUAGE_ENGLISH = ".bghome .dropdown-menu li a:first-child"  # "English" is first

SEL_COUNTRY_INPUT = ".bghome input[placeholder*='Country']"
# Pakistan option — after English selected, country list shows

SEL_BOOK_APPOINTMENT_LINK = [
    "a[href='/schedule']",
    "a:has-text('Book Appointment')",
]

# =============================================================================
# SELECTORS — Login form (/schedule)
# From live screenshot:
#   - "Individual" tab (already selected)
#   - Passport Number *  → input field
#   - Visa Number *      → input field (NOT "VRN")
#   - Captcha Code *     → image + input + refresh button
#   - Submit button
#   - NO mobile/email on this page
# =============================================================================

SEL_PASSPORT_INPUT = [
    "input[formcontrolname*='passport' i]",
    "input[name*='passport' i]",
    "input[placeholder*='Passport' i]",
]

SEL_VISA_INPUT = [
    "input[formcontrolname*='visa' i]",
    "input[name*='visa' i]",
    "input[placeholder*='Visa' i]",
]

# From live DOM:
#   <img id="captchaImage" src="data:image/jpeg;base64,...">
#   <input type="text" name="captcha" placeholder="Enter Captcha">
#   <img src="assets/images/refresh_icon.gif" class="refresh">

SEL_CAPTCHA_IMAGE = [
    "#captchaImage",                     # Exact ID from DOM
    "img[id='captchaImage']",
    "#captchablock img",                 # Inside captchablock div
    "img[src*='captcha' i]",
    "img[src^='data:image']",            # Base64 encoded image
]

SEL_CAPTCHA_INPUT = [
    "input[name='captcha']",             # Exact name from DOM
    "input[placeholder='Enter Captcha']", # Exact placeholder from DOM
    "input[name*='captcha' i]",
    "input[placeholder*='Captcha' i]",
]

SEL_CAPTCHA_REFRESH = [
    "img.refresh",                       # Exact class from DOM
    ".refresh-icon img",                 # Parent div > img
    "img[src*='refresh']",              # Src-based
]

SEL_SUBMIT_BUTTON = [
    "button.btn-brand-arrow",            # Exact class from DOM
    "button:has-text('Submit')",
    "input[type='submit']",
    ".btn:has-text('Submit')",
]

# Notification modal ("Some Exception Occured")
SEL_NOTIFICATION_MODAL = [
    "modal .modal[style*='display: block']",
    "modal .modal[style*='display:block']",
]

SEL_NOTIFICATION_OK = [
    "modal .modal[style*='display: block'] button:has-text('OK')",
    "modal button:has-text('OK')",
]

# "Please enter valid Captcha" error text
SEL_CAPTCHA_ERROR = [
    "span:has-text('valid Captcha')",
    "div:has-text('valid Captcha')",
    ".text-danger:has-text('Captcha')",
]


# =============================================================================
# Helpers
# =============================================================================

async def _query_first(page: Page, selectors: list[str]):
    """Find first matching element."""
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                return el
        except Exception:
            continue
    return None


async def _find_and_fill(page: Page, selectors: list[str], value: str, field_name: str) -> bool:
    """
    Find an input field and fill it.
    Triggers Angular change detection via input/change events.
    """
    if not value:
        logger.debug(f"No value for {field_name}, skipping")
        return False

    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await el.fill("")
                await el.type(value, delay=30)
                # Trigger Angular's form validation
                await el.dispatch_event("input")
                await el.dispatch_event("change")
                await el.dispatch_event("blur")
                logger.info(f"Filled {field_name}")
                return True
        except Exception:
            continue

    logger.warning(f"Could not find input for {field_name}")
    return False


async def _find_and_click(page: Page, selectors: list[str], name: str) -> bool:
    """Find a button/link and click it. Waits briefly for it to enable if disabled."""
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                # Wait up to 3s for button to become enabled
                for _ in range(6):
                    disabled = await el.get_attribute("disabled")
                    if disabled is None:
                        await el.click()
                        logger.info(f"Clicked {name}")
                        return True
                    await asyncio.sleep(0.5)

                # Still disabled — force-enable via JS and click
                logger.warning(f"{name} still disabled — force-enabling")
                await page.evaluate("el => el.removeAttribute('disabled')", el)
                await el.click()
                logger.info(f"Clicked {name} (force-enabled)")
                return True
        except Exception:
            continue

    logger.warning(f"Could not find {name}")
    return False


async def _refresh_captcha(page: Page):
    """Click the CAPTCHA refresh button to get a new image."""
    for sel in SEL_CAPTCHA_REFRESH:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                await asyncio.sleep(1)  # Wait for new CAPTCHA to load
                logger.info("CAPTCHA refreshed")
                return
        except Exception:
            continue
    logger.debug("Could not find CAPTCHA refresh button")


async def _dismiss_notification(page: Page):
    """Dismiss any 'Some Exception Occured' or similar notification modal."""
    ok_btn = await _query_first(page, SEL_NOTIFICATION_OK)
    if ok_btn:
        await ok_btn.click()
        await asyncio.sleep(0.5)
        logger.info("Notification modal dismissed")
        return True

    # Also try the X close button
    close_btn = await page.query_selector("modal .modal[style*='display: block'] .close")
    if close_btn:
        await close_btn.click()
        await asyncio.sleep(0.5)
        return True

    return False


async def _screenshot_and_solve_captcha(page: Page, telegram: TelegramNotifier) -> str | None:
    """
    Screenshot CAPTCHA, send to Telegram, wait for reply.
    Also watches for URL change (user solved CAPTCHA manually in browser).
    Returns:
      - CAPTCHA text if replied via Telegram
      - "__MANUAL__" if user solved it in browser (URL changed)
      - None if timeout
    """
    from captcha_solver import solve_captcha_image, solve_captcha_base64

    # Wait for CAPTCHA image to render (Angular may still be loading)
    captcha_img = None
    for _ in range(5):
        captcha_img = await _query_first(page, SEL_CAPTCHA_IMAGE)
        if captcha_img:
            break
        await asyncio.sleep(0.5)

    screenshot_path = config.SCREENSHOT_DIR / f"captcha1_{datetime.now().strftime('%H%M%S')}.png"

    if captcha_img:
        await captcha_img.screenshot(path=str(screenshot_path))
        logger.info("CAPTCHA image captured")
    else:
        logger.warning("CAPTCHA image element not found — full page screenshot")
        await page.screenshot(path=str(screenshot_path))

    # --- Try AI auto-solve first (Ollama Cloud) ---
    ai_solution = None

    # Try from base64 src (more reliable — no screenshot compression)
    if captcha_img:
        try:
            src = await captcha_img.get_attribute("src")
            if src and src.startswith("data:image"):
                # Extract base64 data after the comma
                b64_data = src.split(",", 1)[1] if "," in src else None
                if b64_data:
                    ai_solution = await solve_captcha_base64(b64_data)
        except Exception as e:
            logger.debug(f"Base64 CAPTCHA extract failed: {e}")

    # Fallback: try from screenshot file
    if not ai_solution:
        ai_solution = await solve_captcha_image(str(screenshot_path))

    if ai_solution:
        logger.info(f"AI auto-solved CAPTCHA: '{ai_solution}'")
        await telegram.send_message(f"AI solved CAPTCHA: {ai_solution}")
        return ai_solution

    # --- AI failed — fall back to Telegram + manual ---
    logger.info("AI solver unavailable or failed — waiting for Telegram reply or manual solve")
    await telegram.send_photo(
        str(screenshot_path),
        caption="CAPTCHA — Reply with the text, or solve it in the browser:"
    )

    # Race: wait for Telegram reply OR detect URL change (manual solve)
    start_url = page.url
    deadline = asyncio.get_running_loop().time() + config.CAPTCHA_TIMEOUT

    # Clear telegram reply state
    if telegram._reply_event:
        telegram._reply_event.clear()
    telegram._reply_text = ""

    while asyncio.get_running_loop().time() < deadline:
        # Check if Telegram reply arrived
        if telegram._reply_event and telegram._reply_event.is_set():
            solution = telegram._reply_text
            logger.info(f"CAPTCHA solution received via Telegram: {len(solution)} chars")
            return solution

        # Check if URL changed to a known next page (user solved CAPTCHA in browser)
        try:
            current_url = page.url
            if any(p in current_url for p in ["applicantdetails", "slotdetails"]):
                if current_url != start_url:
                    logger.info(f"Page advanced during CAPTCHA wait: {current_url}")
                    await telegram.send_message("Detected manual CAPTCHA solve in browser. Continuing...")
                    return "__MANUAL__"
        except Exception:
            pass

        await asyncio.sleep(0.5)

    logger.warning("CAPTCHA timeout — no reply and no URL change")
    return None


# =============================================================================
# Main flows
# =============================================================================

async def select_pakistan_english(page: Page) -> bool:
    """
    Select Pakistan + English on the QVC root page.

    Root page DOM structure:
      <div class="bghome">
        <label>Choose applicant language and country of residence...</label>
        <div class="dropdown">
          <input placeholder="-- Select Language --" data-bs-toggle="dropdown">
          <ul class="dropdown-menu">
            <li>
              <a>English</a>    ← Step 1: click this
              <a>عربى</a>
              <a>اردو</a>
              ...
            </li>
          </ul>
        </div>
        <!-- After selecting language, a country dropdown appears -->
      </div>

    After selecting language + country, the site navigates to /home.
    """
    logger.info("Selecting Pakistan - English on root page...")

    # --- Step 1: Select Language = English ---
    # Click the language dropdown to open it
    lang_input = await page.query_selector(
        ".bghome input[placeholder*='Select Language']"
    )
    if not lang_input:
        lang_input = await page.query_selector(
            "input[placeholder*='Language']"
        )

    if lang_input:
        await lang_input.click()
        await asyncio.sleep(1)  # Wait for dropdown to open

        # Click "English" in the dropdown
        english_option = await page.query_selector(
            ".bghome .dropdown-menu li a:first-child"
        )
        if not english_option:
            # Try text-based selector
            english_option = await page.query_selector("a:has-text('English')")

        if english_option:
            await english_option.click()
            logger.info("Selected language: English")
            await asyncio.sleep(2)  # Wait for country dropdown to appear
        else:
            logger.warning("Could not find 'English' option in language dropdown")
    else:
        logger.warning("Language dropdown not found on root page")

    # --- Step 2: Select Country = Pakistan ---
    # After selecting language, a country dropdown should appear
    # Wait for Angular to render it
    await asyncio.sleep(2)

    # Try to find and click the country dropdown
    country_input = await page.query_selector(
        ".bghome input[placeholder*='Select Country']"
    )
    if not country_input:
        country_input = await page.query_selector(
            "input[placeholder*='Country']"
        )

    if country_input:
        await country_input.click()
        await asyncio.sleep(1)  # Wait for dropdown to open

        # Click "Pakistan" in the country dropdown
        # Try multiple approaches
        pak_option = await page.query_selector(
            ".bghome .dropdown-menu.show a:has-text('Pakistan')"
        )
        if not pak_option:
            pak_option = await page.query_selector("a:has-text('Pakistan')")

        if pak_option:
            # Clicking Pakistan triggers navigation to /home
            # Wait for the navigation to complete
            try:
                async with page.expect_navigation(timeout=15000, wait_until="domcontentloaded"):
                    await pak_option.click()
                logger.info("Selected Pakistan — page navigated to /home")
                await asyncio.sleep(3)  # Wait for /home to fully render
                return True
            except Exception:
                # Navigation may have already happened
                await asyncio.sleep(2)
                if "/home" in page.url or "/schedule" in page.url:
                    logger.info(f"Already on {page.url}")
                    return True
        else:
            logger.warning("Could not find 'Pakistan' in country dropdown")
    else:
        logger.info("No country dropdown found")

    # --- Fallback: Set sessionStorage and navigate directly ---
    try:
        await page.evaluate("""() => {
            sessionStorage.setItem('selectedCountry', JSON.stringify({
                "countryCode": "PK",
                "countryName": "Pakistan",
                "languageCode": "en",
                "languageName": "English",
                "isAppointmentBookingEnabled": true,
                "isManageAppointmentEnabled": true,
                "isTrackApplicationEnabled": true
            }));
        }""")
    except Exception:
        pass

    # Check current URL
    try:
        if "/home" in page.url or "/schedule" in page.url:
            return True
    except Exception:
        pass

    # Navigate to /home directly
    try:
        await page.goto(
            "https://www.qatarvisacenter.com/home",
            wait_until="domcontentloaded",
            timeout=15000
        )
        await asyncio.sleep(2)
        return True
    except Exception as e:
        logger.error(f"Failed to navigate to /home: {e}")

    return False


async def dismiss_all_popups(page: Page):
    """
    Dismiss any notification popups/modals on the page.
    The /schedule page shows an "ATTENTION" popup about fake contact numbers
    with X close button and OK button at the bottom.
    """
    for _ in range(5):  # Try multiple times (could be stacked modals)
        dismissed = False

        # Try X close button (top right of modal)
        for sel in [
            "modal .modal[style*='display: block'] .close",
            ".modal.show .close",
            "button.close:visible",
            ".modal .close",
        ]:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
                    dismissed = True
                    logger.info("Dismissed popup via X button")
                    break
            except Exception:
                continue

        if dismissed:
            continue

        # Try OK button
        for sel in [
            "modal .modal[style*='display: block'] button:has-text('OK')",
            "modal button:has-text('OK')",
            ".modal.show button:has-text('OK')",
            "button:has-text('OK')",
        ]:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
                    dismissed = True
                    logger.info("Dismissed popup via OK button")
                    break
            except Exception:
                continue

        if not dismissed:
            break  # No more popups

    await asyncio.sleep(0.5)


async def navigate_to_book_appointment(page: Page) -> bool:
    """Click 'Book Appointment' link, dismiss any popups, wait for form."""
    logger.info("Navigating to Book Appointment...")

    # Try clicking the nav link
    clicked = await _find_and_click(page, SEL_BOOK_APPOINTMENT_LINK, "Book Appointment")
    if not clicked:
        # Fallback: navigate directly
        try:
            await page.goto(
                "https://www.qatarvisacenter.com/schedule",
                wait_until="domcontentloaded",
                timeout=15000
            )
        except Exception as e:
            logger.error(f"Failed to navigate to /schedule: {e}")
            return False

    await asyncio.sleep(3)  # Wait for /schedule Angular components to render

    # Dismiss any notification popups (ATTENTION about fake numbers, etc.)
    await dismiss_all_popups(page)

    # Wait for the form to be visible
    for _ in range(10):
        passport_field = await _query_first(page, SEL_PASSPORT_INPUT)
        if passport_field:
            logger.info("Login form is visible")
            return True
        # Maybe another popup appeared
        await dismiss_all_popups(page)
        await asyncio.sleep(1)

    logger.warning("Login form not found after navigation")
    return True  # Return True anyway — let auto_fill_and_submit handle it


async def auto_fill_and_submit(page: Page, telegram: TelegramNotifier, city: dict,
                               max_captcha_attempts: int = 3) -> bool:
    """
    Full auto-login: root → English → Pakistan → Book Appointment → form → CAPTCHA → calendar.

    Only user action: reply to CAPTCHA on Telegram.
    Retries CAPTCHA up to 3 times with refresh if it fails.

    Returns True if calendar page was reached.
    """
    city_name = city["name"]

    logger.info(f"Auto-login starting for {city_name}...")
    await telegram.send_message(
        f"Auto-login starting ({city_name})...\n"
        "Auto-filling Passport + Visa Number.\n"
        "Reply with CAPTCHA text when asked."
    )

    # --- Step 1: Navigate to root ---
    try:
        await page.goto(
            "https://www.qatarvisacenter.com",
            wait_until="domcontentloaded",
            timeout=30000
        )
        await asyncio.sleep(2)
    except Exception as e:
        logger.error(f"Navigation failed: {e}")
        await telegram.send_message(f"Navigation failed: {e}")
        return False

    # --- Step 2: Select Pakistan - English ---
    if not await select_pakistan_english(page):
        await telegram.send_message("Could not select country.")
        return False
    await asyncio.sleep(3)  # Wait for Angular to fully render /home

    # --- Step 3: Book Appointment ---
    if not await navigate_to_book_appointment(page):
        await telegram.send_message("Could not reach Book Appointment.")
        return False
    await asyncio.sleep(2)

    # --- Step 4: Fill Passport + Visa Number ---
    filled_pp = await _find_and_fill(page, SEL_PASSPORT_INPUT, config.PASSPORT_NUMBER, "Passport Number")
    filled_visa = await _find_and_fill(page, SEL_VISA_INPUT, config.VISA_REF_NUMBER, "Visa Number")

    if not filled_pp and not filled_visa:
        logger.error("Could not fill Passport/Visa fields — form not found")
        await telegram.send_message("Auto-fill FAILED — form fields not found. Fill manually.")
        return False

    await asyncio.sleep(0.5)

    # --- Step 5-6: CAPTCHA + Submit (with retry) ---
    for attempt in range(1, max_captcha_attempts + 1):
        logger.info(f"CAPTCHA attempt {attempt}/{max_captcha_attempts}")

        if attempt > 1:
            await _refresh_captcha(page)
            await asyncio.sleep(0.5)
            await telegram.send_message(
                f"CAPTCHA was wrong. Refreshed. Attempt {attempt}/{max_captcha_attempts}..."
            )

        # Screenshot → Telegram → wait for reply (or detect manual solve)
        solution = await _screenshot_and_solve_captcha(page, telegram)

        # User solved CAPTCHA manually in browser — page already advanced
        if solution == "__MANUAL__":
            logger.info("Manual CAPTCHA solve detected — skipping to next page")
            # Check where we are now
            await asyncio.sleep(1)
            if "applicantdetails" in page.url:
                result = await fill_contact_details_and_proceed(page, telegram, city_name)
                if result:
                    return True
            if "slotdetails" in page.url:
                await telegram.send_message(f"Calendar loaded ({city_name})!")
                return True
            # Unknown page — let the outer loop figure it out
            return True

        if not solution:
            if attempt == max_captcha_attempts:
                await telegram.send_message("No reply. All attempts used. Solve manually.")
                return False
            continue

        # Fill CAPTCHA
        captcha_input = await _query_first(page, SEL_CAPTCHA_INPUT)
        if captcha_input:
            await captcha_input.fill("")
            await captcha_input.type(solution, delay=30)
            await captcha_input.dispatch_event("input")
            await captcha_input.dispatch_event("change")

        await asyncio.sleep(0.3)

        # Click Submit
        if not await _find_and_click(page, SEL_SUBMIT_BUTTON, "Submit"):
            continue

        await asyncio.sleep(3)  # Wait for server response + page transition

        # --- Handle "active session" dialog ---
        # modal#invalidOldToken: "Appointment booking for the given VRN and Passport
        # number already is in progress. Do you want to clear the current active session?"
        # Buttons: OK | Cancel — must click OK
        for _ in range(3):
            try:
                # Try specific modal ID first
                ok_btn = await page.query_selector(
                    "modal#invalidOldToken .modal[style*='display: block'] button:has-text('OK')"
                )
                if not ok_btn:
                    # Fallback: any visible modal with OK
                    ok_btn = await page.query_selector(
                        "modal .modal[style*='display: block'] button:has-text('OK')"
                    )
                if not ok_btn:
                    ok_btn = await page.query_selector(
                        "modal .modal.fade.in button:has-text('OK')"
                    )
                if ok_btn and await ok_btn.is_visible():
                    await ok_btn.click()
                    logger.info("Dismissed 'active session' dialog — clicked OK")
                    await asyncio.sleep(2)

                    # Check if page already advanced (CAPTCHA was accepted before dialog)
                    await asyncio.sleep(2)
                    if "applicantdetails" in page.url:
                        logger.info("Active session cleared — already on contact details!")
                        await telegram.send_message("Session cleared. Filling contact details...")
                        result = await fill_contact_details_and_proceed(page, telegram, city_name)
                        if result:
                            return True
                    if "slotdetails" in page.url:
                        logger.info("Active session cleared — already on calendar!")
                        return True

                    # Still on same page — CAPTCHA auto-refreshed, need to re-solve
                    logger.info("Active session cleared — CAPTCHA refreshed, re-solving...")
                    await asyncio.sleep(1)

                    # Clear old CAPTCHA answer
                    captcha_input2 = await _query_first(page, SEL_CAPTCHA_INPUT)
                    if captcha_input2:
                        await captcha_input2.fill("")

                    # Screenshot new CAPTCHA → Telegram → wait for reply
                    await telegram.send_message("Session cleared! New CAPTCHA needed...")
                    solution2 = await _screenshot_and_solve_captcha(page, telegram)
                    if solution2:
                        captcha_input2 = await _query_first(page, SEL_CAPTCHA_INPUT)
                        if captcha_input2:
                            await captcha_input2.fill("")
                            await captcha_input2.type(solution2, delay=30)
                        await asyncio.sleep(0.3)
                        await _find_and_click(page, SEL_SUBMIT_BUTTON, "Submit (after session clear)")
                        await asyncio.sleep(3)

                        # Handle another active session dialog if it appears again
                        ok_again = await page.query_selector(
                            "modal#invalidOldToken .modal[style*='display: block'] button:has-text('OK')"
                        )
                        if ok_again and await ok_again.is_visible():
                            await ok_again.click()
                            await asyncio.sleep(2)
                else:
                    break
            except Exception:
                break

        await asyncio.sleep(3)  # Wait for page transition after dialog dismiss

        # --- Check what happened after submit ---
        current_url = page.url

        # SUCCESS: URL changed to applicantdetails = CAPTCHA was correct
        if "applicantdetails" in current_url:
            logger.info("CAPTCHA accepted! Now on contact details page.")
            await telegram.send_message("CAPTCHA accepted! Filling contact details...")

            result = await fill_contact_details_and_proceed(page, telegram, city_name)
            if result:
                return True
            continue  # If contact page failed, try again

        # SUCCESS: Already on calendar (slotdetails)
        if "slotdetails" in current_url:
            logger.info("Calendar reached directly!")
            await telegram.send_message(f"Login successful! Calendar loaded ({city_name}).")
            return True

        # FAIL: Still on same page — check for error modals
        if await _dismiss_notification(page):
            logger.warning("Error modal after submit — retrying CAPTCHA")
            continue

        if await _query_first(page, SEL_CAPTCHA_ERROR):
            logger.warning("Invalid CAPTCHA error")
            continue

        # Unknown state — wait a bit and check
        for _ in range(5):
            await asyncio.sleep(1)
            if "applicantdetails" in page.url:
                result = await fill_contact_details_and_proceed(page, telegram, city_name)
                if result:
                    return True
            calendar = await page.query_selector("sb-datepicker")
            if calendar:
                await telegram.send_message(f"Login successful! ({city_name})")
                return True

    await telegram.send_message("Auto-login failed. Complete manually. Bot waits for calendar.")
    return False


async def fill_contact_details_and_proceed(page: Page, telegram: TelegramNotifier,
                                            city_name: str) -> bool:
    """
    Fill /schedule/applicantdetails page.

    Page structure:
      Primary Contact:
        - Mobile Number *          → input[type='tel'] (1st)
        - Email ID *               → input[type='email'] (1st)
        - [x] Copy primary contact details (only e-mail address will be copied)
      Applicant Information:
        - Mobile Number [Optional]  → input[type='tel'] (2nd) — must fill manually
        - Email ID *                → input[type='email'] (2nd) — copied by checkbox
      Applicant details (read-only): Passport, Visa, Name, DOB, etc.
      Button: "I confirm that the details above are accurate and I am the primary applicant"
    """
    logger.info("Filling contact details page...")
    await asyncio.sleep(1)

    await dismiss_all_popups(page)

    # Get all mobile and email fields
    mobile_fields = await page.query_selector_all("input[type='tel']")
    email_fields = await page.query_selector_all("input[type='email']")

    # Fill PRIMARY CONTACT Mobile (1st tel field)
    if mobile_fields and config.MOBILE_NUMBER:
        await mobile_fields[0].click()
        await mobile_fields[0].fill("")
        await mobile_fields[0].type(config.MOBILE_NUMBER, delay=30)
        logger.info("Filled Primary Mobile")

    # Fill PRIMARY CONTACT Email (1st email field)
    if email_fields and config.EMAIL_ADDRESS:
        await email_fields[0].click()
        await email_fields[0].fill("")
        await email_fields[0].type(config.EMAIL_ADDRESS, delay=30)
        logger.info("Filled Primary Email")

    await asyncio.sleep(0.3)

    # Check "Copy primary contact details" (copies email only)
    copy_checkbox = await page.query_selector("input[type='checkbox']")
    if copy_checkbox:
        checked = await copy_checkbox.is_checked()
        if not checked:
            await copy_checkbox.click()
            logger.info("Checked 'Copy primary contact details'")
            await asyncio.sleep(0.5)

    # Fill APPLICANT Mobile (2nd tel field) — checkbox does NOT copy mobile
    if len(mobile_fields) > 1 and config.MOBILE_NUMBER:
        await mobile_fields[1].click()
        await mobile_fields[1].fill("")
        await mobile_fields[1].type(config.MOBILE_NUMBER, delay=30)
        logger.info("Filled Applicant Mobile")

    # Fill APPLICANT Email (2nd email field) if checkbox didn't copy it
    if len(email_fields) > 1 and config.EMAIL_ADDRESS:
        val = await email_fields[1].input_value()
        if not val:
            await email_fields[1].click()
            await email_fields[1].fill("")
            await email_fields[1].type(config.EMAIL_ADDRESS, delay=30)
            logger.info("Filled Applicant Email")

    await asyncio.sleep(0.5)

    # Click "I confirm that the details above are accurate..."
    submitted = False

    # Find the confirm button
    confirm_btn = None
    for sel in [
        "button:has-text('I confirm')",
        "button:has-text('confirm')",
        "button:has-text('primary applicant')",
    ]:
        try:
            confirm_btn = await page.query_selector(sel)
            if confirm_btn:
                break
        except Exception:
            continue

    if not confirm_btn:
        # Try finding by iterating all buttons
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            try:
                text = await btn.text_content()
                if text and "confirm" in text.lower():
                    confirm_btn = btn
                    break
            except Exception:
                continue

    if confirm_btn:
        # Scroll the button into view and wait for Angular form validation
        await confirm_btn.scroll_into_view_if_needed()
        await asyncio.sleep(2)  # Let Angular validate all fields before clicking

        url_before = page.url

        # Try multiple click strategies
        for click_attempt in range(3):
            try:
                if click_attempt == 0:
                    await confirm_btn.click(timeout=3000)
                    logger.info("Clicked 'I confirm' (Playwright click)")
                elif click_attempt == 1:
                    await page.evaluate("btn => btn.click()", confirm_btn)
                    logger.info("Clicked 'I confirm' (JS click)")
                else:
                    # Force click at element's coordinates
                    box = await confirm_btn.bounding_box()
                    if box:
                        await page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                        logger.info("Clicked 'I confirm' (mouse coordinate click)")

                submitted = True
                await asyncio.sleep(3)

                # Check if URL changed (success) or popup appeared
                if page.url != url_before:
                    logger.info(f"Page navigated to {page.url}")
                    break

                # Dismiss any popup that appeared
                await dismiss_all_popups(page)
                await asyncio.sleep(1)

                # Check again after dismissing popup
                if page.url != url_before:
                    break

                # URL didn't change — try next click strategy
                if click_attempt < 2:
                    logger.warning(f"Click attempt {click_attempt+1} didn't navigate — trying next strategy")
                    # Re-find the button in case DOM changed
                    confirm_btn = await page.query_selector("button:has-text('I confirm')")
                    if not confirm_btn:
                        break

            except Exception as e:
                logger.warning(f"Click attempt {click_attempt+1} error: {e}")
    else:
        logger.warning("Could not find confirm button")
        await telegram.send_message("Could not find confirm. Click it manually in browser.")

    await asyncio.sleep(2)
    await dismiss_all_popups(page)

    # Wait for calendar page
    await telegram.send_message("Contact details submitted! Waiting for calendar...")
    for _ in range(30):
        current = page.url
        if "slotdetails" in current:
            calendar = await page.query_selector("sb-datepicker")
            if calendar:
                logger.info("Calendar reached after contact details!")
                await telegram.send_message(f"Login complete! Calendar loaded ({city_name}).")
                return True
        # Still on applicantdetails — maybe button didn't work
        if "applicantdetails" in current:
            # Try clicking confirm again
            btn = await page.query_selector("button:has-text('I confirm')")
            if btn:
                try:
                    await btn.scroll_into_view_if_needed()
                    await page.evaluate("btn => btn.click()", btn)
                    logger.info("Re-clicked confirm button")
                except Exception:
                    pass
        await dismiss_all_popups(page)
        await asyncio.sleep(1)

    logger.warning("Calendar not reached after contact details")
    await telegram.send_message("Calendar not found. Check browser — click 'I confirm' manually if needed.")
    return False
