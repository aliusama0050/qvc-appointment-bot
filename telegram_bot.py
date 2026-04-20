"""
QVC Appointment Booking Bot - Telegram Integration
Sends screenshots/notifications and receives CAPTCHA solutions.
Includes retry logic for unreliable proxy connections.
"""

import asyncio
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

import config

logger = logging.getLogger("qvc.telegram")

# Custom Telegram API URL (Cloudflare Worker proxy)
# If set, the bot sends requests to this URL instead of api.telegram.org
# Example: https://my-telegram-proxy.username.workers.dev
TELEGRAM_API_URL = config.TELEGRAM_API_URL if hasattr(config, "TELEGRAM_API_URL") else ""

# Fallback HTTP proxies (unreliable — prefer Cloudflare Worker)
FALLBACK_PROXIES = [
    "http://185.41.152.110:3128",
    "http://185.191.236.162:3128",
    "http://116.80.60.44:7777",
]


class TelegramNotifier:
    """Handles all Telegram communication: sending messages/photos and receiving replies."""

    def __init__(self):
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.app: Application | None = None

        # For receiving CAPTCHA replies
        self._reply_event: asyncio.Event | None = None
        self._reply_text: str = ""

    def _build_app(self, proxy_url: str = "", base_url: str = "") -> Application:
        """Build a Telegram Application with optional proxy or custom API URL."""
        builder = Application.builder().token(self.token)

        if base_url:
            # Cloudflare Worker proxy — custom base URL, no HTTP proxy needed
            api_url = base_url.rstrip("/") + "/bot"
            builder = builder.base_url(api_url).base_file_url(api_url)
            # Worker route can be slow from Pakistan — generous timeouts
            request = HTTPXRequest(connect_timeout=120.0, read_timeout=120.0)
            builder = builder.request(request).get_updates_request(
                HTTPXRequest(connect_timeout=120.0, read_timeout=120.0)
            )
        elif proxy_url:
            request = HTTPXRequest(proxy=proxy_url, connect_timeout=30.0, read_timeout=30.0)
            builder = builder.request(request).get_updates_request(
                HTTPXRequest(proxy=proxy_url, connect_timeout=30.0, read_timeout=30.0)
            )

        return builder.build()

    async def _try_start_with_proxy(self, proxy_url: str) -> bool:
        """Try to initialize the bot with a specific proxy. Returns True on success."""
        try:
            logger.info(f"Trying proxy: {proxy_url or 'direct (no proxy)'}")
            self.app = self._build_app(proxy_url)

            self.app.add_handler(
                MessageHandler(
                    filters.TEXT & filters.Chat(self.chat_id),
                    self._on_message,
                )
            )

            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)
            logger.info(f"Telegram bot connected via: {proxy_url or 'direct'}")
            return True
        except Exception as e:
            logger.warning(f"Proxy failed ({proxy_url}): {type(e).__name__}: {e}")
            # Clean up failed app
            try:
                if self.app:
                    await self.app.shutdown()
            except Exception:
                pass
            self.app = None
            return False

    async def _try_start_with_base_url(self, base_url: str) -> bool:
        """Try to initialize the bot with a custom API base URL (Cloudflare Worker)."""
        try:
            logger.info(f"Trying Cloudflare Worker: {base_url}")
            self.app = self._build_app(base_url=base_url)

            self.app.add_handler(
                MessageHandler(
                    filters.TEXT & filters.Chat(self.chat_id),
                    self._on_message,
                )
            )

            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling(drop_pending_updates=True)
            logger.info(f"Telegram bot connected via Cloudflare Worker: {base_url}")
            return True
        except Exception as e:
            logger.warning(f"Cloudflare Worker failed ({base_url}): {type(e).__name__}: {e}")
            try:
                if self.app:
                    await self.app.shutdown()
            except Exception:
                pass
            self.app = None
            return False

    async def start(self):
        """Start the Telegram bot. Tries in order: Cloudflare Worker → proxy → direct."""
        self._reply_event = asyncio.Event()

        # 1. Try Cloudflare Worker proxy (most reliable) — retry up to 3 times
        if TELEGRAM_API_URL:
            for attempt in range(1, 4):
                logger.info(f"Cloudflare Worker attempt {attempt}/3...")
                if await self._try_start_with_base_url(TELEGRAM_API_URL):
                    return
                if attempt < 3:
                    logger.info("Retrying Worker in 5s...")
                    await asyncio.sleep(5)

        # 2. Try HTTP proxies: configured first, then fallbacks, then direct
        proxies_to_try = []
        if config.PROXY_URL:
            proxies_to_try.append(config.PROXY_URL)
        for fb in FALLBACK_PROXIES:
            if fb != config.PROXY_URL:
                proxies_to_try.append(fb)
        proxies_to_try.append("")  # Direct connection as last resort

        for proxy in proxies_to_try:
            if await self._try_start_with_proxy(proxy):
                return

        raise RuntimeError(
            "Could not connect to Telegram API.\n"
            "Options:\n"
            "  1. Set TELEGRAM_API_URL to a Cloudflare Worker (see telegram-proxy-worker.js)\n"
            "  2. Set PROXY_URL to a working HTTP proxy\n"
            "  3. Use a VPN and leave PROXY_URL empty"
        )

    async def stop(self):
        """Shut down the Telegram bot cleanly."""
        if self.app:
            try:
                await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
            except Exception as e:
                logger.debug(f"Telegram shutdown error (safe to ignore): {e}")
            logger.info("Telegram bot stopped")

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages — store as CAPTCHA reply if waiting."""
        if update.message and update.message.text:
            text = update.message.text.strip()
            logger.info(f"Received Telegram message: {text}")
            self._reply_text = text
            if self._reply_event:
                self._reply_event.set()

    async def send_message(self, text: str):
        """Send a text message with retry on failure."""
        if not self.app:
            logger.error("Telegram app not started, cannot send message")
            return
        for attempt in range(3):
            try:
                await self.app.bot.send_message(chat_id=self.chat_id, text=text)
                logger.info(f"Sent message: {text[:80]}")
                return
            except Exception as e:
                logger.warning(f"Send message attempt {attempt+1}/3 failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2)
        logger.error(f"Failed to send message after 3 attempts: {text[:80]}")

    async def send_photo(self, image_path: str | Path, caption: str = ""):
        """Send a photo with retry on failure."""
        if not self.app:
            logger.error("Telegram app not started, cannot send photo")
            return
        for attempt in range(3):
            try:
                with open(image_path, "rb") as photo:
                    await self.app.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=photo,
                        caption=caption,
                    )
                logger.info(f"Sent photo: {image_path}")
                return
            except Exception as e:
                logger.warning(f"Send photo attempt {attempt+1}/3 failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2)
        logger.error(f"Failed to send photo after 3 attempts")

    async def wait_for_reply(self, timeout: float = None) -> str | None:
        """
        Wait for the user to reply via Telegram.
        Returns the reply text, or None if timeout expires.
        """
        if not self._reply_event:
            return None

        timeout = timeout or config.CAPTCHA_TIMEOUT
        self._reply_event.clear()
        self._reply_text = ""

        try:
            await asyncio.wait_for(self._reply_event.wait(), timeout=timeout)
            return self._reply_text
        except asyncio.TimeoutError:
            logger.warning(f"No reply received within {timeout}s")
            return None
