"""
QVC Appointment Booking Bot - Session Keepalive & Error Management
Keeps the session alive without page reloads, dismisses error modals,
and controls burst mode when errors spike.
Sends Telegram notifications on all errors and events.
"""

import asyncio
import time
import logging
from playwright.async_api import Page

import config
import dom_selectors as sel
from browser import query_first, get_page_lock

logger = logging.getLogger("qvc.keepalive")

# Will be set by main.py after telegram is initialized
_telegram = None


def set_telegram(telegram):
    """Set the telegram notifier instance for error notifications."""
    global _telegram
    _telegram = telegram


async def _notify(msg: str):
    """Send a notification to Telegram if available."""
    if _telegram:
        try:
            await _telegram.send_message(msg)
        except Exception:
            pass  # Don't let notification failure crash the watcher


class BurstModeController:
    """Tracks error frequency and toggles burst mode."""

    def __init__(self):
        self.error_timestamps: list[float] = []
        self.is_burst = False
        self._burst_until = 0.0

    @property
    def poll_interval(self) -> float:
        """Current poll interval based on burst mode state."""
        if self.is_burst and time.time() < self._burst_until:
            return config.BURST_POLL_INTERVAL
        elif self.is_burst:
            self.is_burst = False
            logger.info("Burst mode ended, reverting to normal polling")
        return config.POLL_INTERVAL

    @property
    def keepalive_interval(self) -> float:
        """Current keepalive interval (shorter during burst)."""
        return 20.0 if self.is_burst else config.KEEPALIVE_INTERVAL

    def record_error(self):
        """Record an error timestamp and check if burst mode should activate."""
        now = time.time()
        self.error_timestamps.append(now)

        cutoff = now - config.BURST_ERROR_WINDOW
        self.error_timestamps = [t for t in self.error_timestamps if t > cutoff]

        if len(self.error_timestamps) >= config.BURST_ERROR_THRESHOLD and not self.is_burst:
            self.is_burst = True
            self._burst_until = now + config.BURST_DURATION
            logger.warning(
                f"BURST MODE ACTIVATED! {len(self.error_timestamps)} errors in "
                f"{config.BURST_ERROR_WINDOW}s. Polling at {config.BURST_POLL_INTERVAL}s "
                f"for {config.BURST_DURATION}s"
            )
            asyncio.create_task(_notify(
                f"BURST MODE ACTIVATED!\n"
                f"{len(self.error_timestamps)} errors in {config.BURST_ERROR_WINDOW}s\n"
                f"Polling speed increased to {config.BURST_POLL_INTERVAL}s for {config.BURST_DURATION}s"
            ))


# Shared burst controller instance
burst = BurstModeController()


async def session_keepalive(page: Page, stop_event: asyncio.Event):
    """
    Periodically ping the session to prevent timeout.
    Uses mouse micro-movement + lightweight JS — no page reload.
    """
    logger.info(f"Session keepalive started (every {config.KEEPALIVE_INTERVAL}s)")
    consecutive_failures = 0

    while not stop_event.is_set():
        try:
            interval = burst.keepalive_interval
            await asyncio.sleep(interval)

            if stop_event.is_set():
                break

            async with get_page_lock():
                # Mouse micro-movement to simulate activity
                await page.mouse.move(400, 300)
                await asyncio.sleep(0.1)
                await page.mouse.move(401, 301)

                # Lightweight JS ping with credentials to keep session cookies alive
                await page.evaluate("""() => {
                    try {
                        fetch('/favicon.ico', {
                            method: 'HEAD',
                            cache: 'no-store',
                            credentials: 'include'
                        }).catch(() => {});
                    } catch(e) {}
                }""")

            logger.debug(f"Keepalive ping sent (interval: {interval}s)")
            consecutive_failures = 0  # Reset on success

        except Exception as e:
            consecutive_failures += 1
            logger.warning(f"Keepalive error: {e}")
            burst.record_error()

            if consecutive_failures == 1:
                await _notify(f"Keepalive ping failed: {type(e).__name__}")
            elif consecutive_failures % 5 == 0:
                await _notify(
                    f"Keepalive failing repeatedly ({consecutive_failures} in a row)\n"
                    f"Session may be at risk!"
                )


async def error_watcher(page: Page, stop_event: asyncio.Event):
    """
    Continuously watch for error modals and dismiss them without page reload.
    Sends Telegram notification for each error detected.
    """
    logger.info("Error watcher started")
    total_dismissed = 0

    while not stop_event.is_set():
        try:
            await asyncio.sleep(1)

            if stop_event.is_set():
                break

            async with get_page_lock():
                modal = await query_first(page, sel.ERROR_MODAL)
                if modal:
                    total_dismissed += 1

                    # Try to get the modal text for the notification
                    modal_text = ""
                    try:
                        modal_text = await modal.text_content()
                        modal_text = (modal_text or "").strip()[:200]
                    except Exception:
                        pass

                    logger.warning(f"Error modal detected! ({total_dismissed} total)")

                    # Try to click the dismiss button
                    dismiss_btn = await query_first(page, sel.ERROR_DISMISS_BUTTON)
                    if dismiss_btn:
                        await dismiss_btn.click()
                        logger.info("Error modal dismissed via button")
                    else:
                        await page.keyboard.press("Escape")
                        logger.info("Error modal dismissed via Escape key")

                    burst.record_error()

                    # Identify the modal type for clearer notifications
                    modal_type = "Unknown error"
                    for modal_id in ["SessionExpired", "webSiteAlert", "ServiceNotAvail",
                                     "UnAuthorised", "slotNotification"]:
                        check = await page.query_selector(
                            f"modal#{('modal' if not modal_id[0].islower() else '')}{modal_id} .modal[style*='display: block']"
                        )
                        if not check:
                            check = await page.query_selector(
                                f"modal#{modal_id} .modal[style*='display: block']"
                            )
                        if check:
                            modal_type = modal_id
                            break

                    # TELEGRAM NOTIFICATION
                    await _notify(
                        f"Error dismissed! (#{total_dismissed})\n"
                        f"Type: {modal_type}\n"
                        f"{'Text: ' + modal_text if modal_text else ''}"
                    )

                    await asyncio.sleep(0.5)

        except Exception as e:
            logger.debug(f"Error watcher iteration error: {e}")
