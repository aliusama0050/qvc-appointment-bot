# QVC Appointment Slot Monitor & Booking Bot

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Playwright-1.40+-green?style=flat-square" alt="Playwright">
  <img src="https://img.shields.io/badge/Telegram-Bot-0088cc?style=flat-square&logo=telegram" alt="Telegram">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License">
</p>

<p align="center">
  <b>Automated visa appointment monitoring & booking automation for Qatar Visa Center Pakistan</b>
</p>

---

## Overview

A sophisticated Python-based automation bot that monitors the Qatar Visa Center (QVC) website for available visa appointment slots in **Islamabad** and **Karachi**. When a slot becomes available, the bot:

- Automatically detects and clicks available dates
- Captures screenshots for confirmation
- Sends instant Telegram alerts with visual feedback
- Handles CAPTCHA solving via Telegram two-way communication
- Maintains persistent browser sessions with automatic recovery

## Features

| Feature | Description |
|---------|-------------|
| **Real-time Monitoring** | Sub-second polling (0.8s) with burst mode (0.3s) for high-traffic periods |
| **Multi-City Support** | Monitor Islamabad and Karachi QVC centers simultaneously |
| **Smart Slot Detection** | Checks 3 months of availability across dynamic Angular calendar |
| **Auto-Booking** | Automatically clicks available slots and notifies user for final confirmation |
| **Two-Way Telegram** | Sends screenshots, receives CAPTCHA solutions, and confirms bookings |
| **AI CAPTCHA Solver** | Optional Ollama Cloud vision model for automatic CAPTCHA resolution |
| **Session Keepalive** | Prevents session expiration with automated ping intervals |
| **Burst Mode** | Automatically accelerates polling when errors spike |
| **Proxy Support** | Built-in HTTP/SOCKS5 proxy fallback + Cloudflare Worker integration |
| **Anti-Detection** | Stealth browser configuration to avoid bot detection |
| **Persistent Browser** | Browser stays open even after script exits for manual completion |

## Quick Start

### Prerequisites

- Python 3.10+
- Playwright browsers installed
- Telegram bot token and chat ID

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/qvc-appointment-bot.git
cd qvc-appointment-bot

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env with your Telegram credentials
```

### Configuration

Edit `.env` with your settings:

```bash
# Required: Telegram Bot Token (from @BotFather)
TELEGRAM_BOT_TOKEN=your_token_here

# Required: Your Telegram Chat ID
TELEGRAM_CHAT_ID=123456789

# Optional: AI CAPTCHA solving (Ollama Cloud)
OLLAMA_API_KEY=your_key_here

# Optional: HTTP/SOCKS5 proxy for Telegram
PROXY_URL=socks5://127.0.0.1:1080
```

### Usage

```bash
# Interactive mode - select city, configure browser
python main.py

# Inspect mode - debug DOM selectors
python main.py --inspect

# Test Telegram connection
python test_telegram.py
```

## How It Works

```
User launches bot → Selects city → Bot logs in → Monitors calendar
                                          ↓
                           ┌───────────────┼───────────────┐
                           ↓               ↓               ↓
                    No slots      Slot found       Session expired
                           ↓               ↓               ↓
                    Continue polling  Auto-click    Auto-recovery
                    (0.8s interval)   date/time     re-login
                           ↓               ↓               ↓
                    Send Telegram  Capture        Continue
                    "No slots"     screenshot       monitoring
                                   ↓
                            CAPTCHA detected
                                   ↓
                    ┌──────────────┴──────────────┐
                    ↓                             ↓
            AI Solver (Ollama)          Telegram Manual Solve
                    ↓                             ↓
            Auto-fill                      User replies
            solution                       with answer
                    ↓                             ↓
                            BOOKING CONFIRMED
                            Send confirmation
                            screenshot
```

## Architecture

```
qvc-appointment-bot/
├── main.py                 # CLI entry point & orchestration
├── config.py               # Environment configuration loader
├── telegram_bot.py         # Telegram API integration (send/receive)
├── calendar_monitor.py     # Calendar polling & slot detection
├── browser.py              # Playwright browser automation
├── auto_login.py           # Session recovery & re-login handler
├── keepalive.py            # Session maintenance & burst mode
├── captcha_solver.py       # AI-powered CAPTCHA solving
├── dom_selectors.py        # Centralized CSS selectors
├── test_telegram.py        # Telegram connectivity test
└── telegram-proxy-worker.js # Cloudflare Worker proxy template
```

## Technical Highlights

### Angular SPA Handling
The QVC website is an Angular Single Page Application. Instead of page reloads, the bot triggers Angular's change detection by re-selecting the city dropdown, forcing fresh API calls without DOM refreshes.

### Session Persistence
Using Playwright's CDP (Chrome DevTools Protocol), the browser remains open even after the Python script exits, allowing users to manually complete bookings in the same browser instance.

### Burst Mode
When errors exceed 3 in 10 seconds, the bot automatically enters "burst mode":
- Polling interval: 0.8s → 0.3s
- Keepalive interval: 40s → 20s
- Duration: 30 seconds
- Notification sent via Telegram

### Proxy Strategy
For regions where Telegram API is blocked (Pakistan/Qatar):
1. **Primary**: Cloudflare Worker proxy (most reliable)
2. **Secondary**: Rotating HTTP proxies
3. **Tertiary**: Direct connection with VPN

## Telegram Notifications

| Event | Notification |
|-------|--------------|
| Bot Ready | "Browser ready! Complete login manually..." |
| Monitoring Active | "Calendar detected! Monitoring for slots..." |
| Status Update | "Still monitoring... Polls: 375, Months: Mar+Apr+May" |
| **Slot Available** | **"SLOT AVAILABLE!"** + calendar screenshot |
| Date Selected | "Date & time selected! Proceeding to CAPTCHA" |
| Burst Mode | "BURST MODE ACTIVATED! 3 errors in 10s" |
| CAPTCHA Required | Screenshot + "Reply with solution" |
| **Booking Confirmed** | **"BOOKING CONFIRMED!"** + confirmation screenshot |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | — | Your Telegram chat ID |
| `TELEGRAM_API_URL` | — | Cloudflare Worker proxy URL |
| `PROXY_URL` | — | HTTP/SOCKS5 proxy |
| `CAPTCHA_MODE` | `telegram` | `telegram` or `manual` |
| `OLLAMA_API_KEY` | — | Ollama Cloud API key |
| `POLL_INTERVAL` | `0.8` | Seconds between calendar checks |
| `BURST_POLL_INTERVAL` | `0.3` | Fast polling during burst mode |
| `KEEPALIVE_INTERVAL` | `40` | Session ping interval (seconds) |
| `CAPTCHA_TIMEOUT` | `120` | Wait time for Telegram reply |

## Troubleshooting

### Browser shows blank page
- Start from root URL, not `/home`
- Select Pakistan first to initialize `sessionStorage`
- Clear `.browser_profile` folder and restart

### Telegram messages not sending
- Verify `PROXY_URL` or `TELEGRAM_API_URL` in `.env`
- Run `python test_telegram.py` to diagnose
- Ensure you pressed "Start" in the Telegram bot chat

### "Session Expired" errors
- Keepalive pings every 40s automatically
- Bot auto-dismisses modals and continues monitoring
- If persistent, session may be rate-limited

### Calendar shows no slots
- This is normal — slots are rare and fill instantly
- Bot checks every 0.8s across 3 months
- Even 1-second availability windows are caught

## Dependencies

```
playwright>=1.40.0          # Browser automation
python-telegram-bot>=20.7   # Telegram Bot API
python-dotenv>=1.0.0        # Environment management
httpx[socks]>=0.27.0        # HTTP client with proxy support
ollama>=0.4.0               # AI CAPTCHA solving
```

## Requirements

- Python 3.10 or higher
- Chromium browser (via Playwright)
- Stable internet connection
- Telegram account

## Legal Disclaimer

This tool is for **personal/educational use only**. Use responsibly and in accordance with Qatar Visa Center terms of service. The author is not responsible for any misuse or violations.

## License

MIT License — see LICENSE file for details.

## Support

- Create an issue for bug reports
- Fork and submit PRs for improvements
- Star the repo if you find it useful!

---

<p align="center">
  <sub>Built with Python, Playwright, and caffeine ☕</sub>
</p>
