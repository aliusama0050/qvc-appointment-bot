"""Quick test: verify Telegram bot token, chat ID, and proxy work."""

import asyncio
import sys
sys.path.insert(0, ".")

import config

config.ensure_dirs()

from telegram_bot import TelegramNotifier


async def test():
    print(f"Token: {config.TELEGRAM_BOT_TOKEN[:10]}...{config.TELEGRAM_BOT_TOKEN[-5:]}")
    print(f"Chat ID: {config.TELEGRAM_CHAT_ID}")
    print(f"Proxy: {config.PROXY_URL or 'None (direct)'}")

    notifier = TelegramNotifier()
    await notifier.start()

    print("Sending test message...")
    await notifier.send_message(
        "QVC Bot test - connection successful!\n"
        "If you see this, the bot token, chat ID, and proxy are all working."
    )
    print("Message sent! Check your Telegram.")

    await notifier.stop()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(test())
