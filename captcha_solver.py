"""
QVC Bot - CAPTCHA Auto-Solver using Ollama Cloud Vision

Uses Ollama Cloud's free tier with a vision model (qwen3-vl) to read
CAPTCHA text from images. Falls back to Telegram if AI fails.

Setup:
  1. Create account at ollama.com
  2. Get API key from ollama.com/settings/keys
  3. Set OLLAMA_API_KEY in .env
"""

import asyncio
import base64
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("qvc.captcha_solver")

# Vision model to use — qwen3-vl is best for text-in-image tasks
VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen3-vl:235b")


async def solve_captcha_image(image_path: str | Path) -> str | None:
    """
    Send CAPTCHA image to Ollama Cloud vision model.
    Returns the solved text or None if it fails.

    The CAPTCHA images from QVC are simple 4-character alphanumeric codes
    (mix of uppercase letters and digits, sometimes with visual noise).
    """
    api_key = os.getenv("OLLAMA_API_KEY", "")
    if not api_key:
        logger.debug("No OLLAMA_API_KEY set — skipping AI solver")
        return None

    try:
        from ollama import Client

        client = Client(
            host="https://ollama.com",
            headers={"Authorization": f"Bearer {api_key}"}
        )

        # Read image and encode as base64
        image_path = Path(image_path)
        if not image_path.exists():
            logger.warning(f"CAPTCHA image not found: {image_path}")
            return None

        image_bytes = image_path.read_bytes()

        logger.info(f"Sending CAPTCHA to Ollama Cloud ({VISION_MODEL})...")

        # Run sync client.chat() in a thread to avoid blocking the event loop
        response = await asyncio.to_thread(
            client.chat,
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    "This is a CAPTCHA image containing a short code of letters and/or numbers. "
                    "Read the exact text shown in the image. "
                    "Reply with ONLY the characters you see — nothing else. "
                    "No explanation, no quotes, no spaces. Just the raw characters."
                ),
                "images": [image_bytes],
            }],
        )

        raw_text = response.message.content.strip()

        # Clean up the response — extract only alphanumeric characters
        cleaned = re.sub(r"[^a-zA-Z0-9]", "", raw_text)

        if not cleaned:
            logger.warning(f"AI returned empty/unusable response: '{raw_text}'")
            return None

        # QVC CAPTCHAs are typically 4 characters
        if len(cleaned) < 3 or len(cleaned) > 8:
            logger.warning(f"AI response length unusual ({len(cleaned)}): '{cleaned}' (raw: '{raw_text}')")
            # Still return it — let the caller decide
            return cleaned.upper()

        logger.info(f"AI solved CAPTCHA: '{cleaned}' (raw: '{raw_text}')")
        return cleaned.upper()

    except ImportError:
        logger.warning("ollama package not installed — run: pip install ollama")
        return None
    except Exception as e:
        logger.warning(f"Ollama Cloud CAPTCHA solve failed: {type(e).__name__}: {e}")
        return None


async def solve_captcha_base64(base64_data: str) -> str | None:
    """
    Solve CAPTCHA from a base64-encoded image string.
    The QVC site embeds CAPTCHA as: src="data:image/jpeg;base64,..."
    """
    api_key = os.getenv("OLLAMA_API_KEY", "")
    if not api_key:
        return None

    try:
        from ollama import Client

        client = Client(
            host="https://ollama.com",
            headers={"Authorization": f"Bearer {api_key}"}
        )

        # Decode base64 to bytes
        image_bytes = base64.b64decode(base64_data)

        logger.info(f"Sending CAPTCHA (base64) to Ollama Cloud ({VISION_MODEL})...")

        # Run sync client.chat() in a thread to avoid blocking the event loop
        response = await asyncio.to_thread(
            client.chat,
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    "This is a CAPTCHA image containing a short code of letters and/or numbers. "
                    "Read the exact text shown in the image. "
                    "Reply with ONLY the characters you see — nothing else. "
                    "No explanation, no quotes, no spaces. Just the raw characters."
                ),
                "images": [image_bytes],
            }],
        )

        raw_text = response.message.content.strip()
        cleaned = re.sub(r"[^a-zA-Z0-9]", "", raw_text)

        if not cleaned:
            logger.warning(f"AI returned empty response: '{raw_text}'")
            return None

        logger.info(f"AI solved CAPTCHA: '{cleaned}' (raw: '{raw_text}')")
        return cleaned.upper()

    except Exception as e:
        logger.warning(f"Ollama CAPTCHA solve failed: {type(e).__name__}: {e}")
        return None
