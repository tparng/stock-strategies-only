# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Taiwan Stock Daily Selection Robot — screens and scores Taiwan stock watchlist daily after market close (14:30 Taiwan time), sends BUY/WATCH/SKIP signals via Telegram with position sizing, and records to Google Sheets. Runs on GitHub Actions (free tier, ~44 min/month). Secondary pre-market session at 08:00 predicts daily market direction from overnight Taiwan futures.

## Commands

**Setup:**
```bash
uv sync                         # Install Python dependencies
cp .env.example .env            # Configure the 5 required secrets (see .env.example)
cd web && npm install           # Install frontend dependencies (optional)
```

**Run:**
```bash
uv run python main.py           # Daily stock selection (14:30 run)
uv run python premarket.py      # Pre-market night session report (08:00 run)
uv run uvicorn api.main:app --reload --port 8000  # FastAPI backend
cd web && npm run dev           # Next.js frontend (requires backend on 8000)
```

**Test:**
```bash
uv run pytest -q                # All unit tests (no real API tokens needed)
uv run pytest tests/factors/test_momentum.py -v  # Single test file
uv run pytest -m live           # Integration tests (requires FINMIND_TOKEN in .env)
```

## Architecture

### Three-layer design

**Layer 1: Data input**
- Google Sheets `Watchlist` tab: user-maintained list of stock IDs to screen
- FinMind API: price history (日K OHLCV) + fundamentals (EPS/ROE) + 7 additional datasets (institutional ownership, monthly revenue, valuations, margin debt, shareholding, index data)
- Parquet cache in `.cache/finmind/` with TTL-based freshness (daily=1d, weekly=5d, monthly=20d, quarterly=60d) and 0.12s rate limiting with exponential backoff

**Layer 2: Scoring engine (two generations coexist)**

*Production V3.2 (main.py → evaluate.py):*
- Fundamental gate: EPS≥5, ROE≥15% for 2+ recent years
- Technical score (4 indicators × 25pts): MA alignment, Bollinger bounce, KD golden cross, MACD bullish
- 3-year historical backtest with fixed 20-day hold, +10%/-8% exits
- Composite: 30% fundamental + 30% technical + 40% backtest → BUY(≥65) / WATCH(50–65) / SKIP(<50)
- Market filter: weighted index monthly MA (hard downgrade BUY→WATCH if below)
- Night session filter: Taiwan futures overnight move sentiment overlay

*Under development V3.4 (stock_strategies/factors/, context.py, cache.py):*
- `FactorContext` dataclass (context.py): point-in-time-safe container for all 7 datasets
- 29 quantitative factors across 7 schools: Value, Growth, Momentum, Chips/Institutional, Revenue, Reversal, Breakout
- Factor registry pattern: `compute_factor(name, ctx, params) → float[0–1]`
- `panel.py`: batch computation across all registered factors

**Layer 3: Output**
- Telegram: three-message push (market overview → stock details → action tips)
- Google Sheets `Signals` tab: each day's picks with scores
- Google Sheets `Performance` tab: realized T+1/5/10/20 returns auto-updated

### Key modules

| File | Responsibility |
|------|---------------|
| `main.py` | Daily orchestrator — chains all layers |
| `premarket.py` | Morning futures preview |
| `stock_strategies/evaluate.py` | Core V3.2 scoring logic |
| `stock_strategies/data.py` | FinMind API calls |
| `stock_strategies/indicators.py` | MA, Bollinger, KD, MACD |
| `stock_strategies/backtest.py` | 3-year trade simulation |
| `stock_strategies/context.py` | V3.4 `FactorContext` dataclass + `build_context()` |
| `stock_strategies/factors/registry.py` | Factor registration + `compute_factor()` |
| `stock_strategies/cache.py` | Parquet caching + rate limiting |
| `stock_strategies/config.py` | All thresholds and constants |
| `stock_strategies/sheet.py` | Google Sheets read/write |
| `stock_strategies/notify.py` | Telegram message formatting |
| `api/main.py` | FastAPI REST endpoints |
| `api/services/ai_generator.py` | Gemini AI strategy generation |
| `web/` | Next.js dashboard (strategy CRUD, AI generator, on-demand runs) |
| `strategies/*.json` | Parameterized strategy definitions; `default.json` holds base values |

### Data flow (main.py)

```
Watchlist (Sheets) → evaluate each stock (fundamentals + technicals + backtest)
→ apply market filter (index monthly MA)
→ apply night session filter (futures overnight %)
→ write Signals sheet + update Performance sheet
→ push 3-message Telegram notification
```

### V3.4 factor data flow

```
build_context(stock_id, as_of) → FactorContext (7 datasets, cached)
→ compute_all_factors(ctx, factor_list) → weighted composite [0–1]
```

## Required Environment Variables

```
FINMIND_TOKEN        # FinMind API token
TELEGRAM_BOT_TOKEN   # Telegram bot auth
TELEGRAM_CHAT_ID     # Destination chat ID
GOOGLE_SHEET_ID      # Google Sheets document ID
GOOGLE_CREDS_JSON    # Service account JSON as full string
```

Optional (V3.3 web UI only):
```
GEMINI_API_KEY       # For AI strategy generation
GEMINI_MODEL         # Default: gemini-2.5-flash
CORS_ORIGINS         # Default: http://localhost:3000
NEXT_PUBLIC_API_BASE # Default: http://localhost:8000
STRATEGY_DIR         # Default: ./strategies
```

## GitHub Actions

- `.github/workflows/daily.yml`: cron `30 6 * * 1-5` (14:30 Taiwan time on weekdays)
- `.github/workflows/premarket.yml`: 08:00 Taiwan time
- All secrets stored as encrypted GitHub Actions secrets (same names as `.env` keys)

## Testing Conventions

- All FinMind API calls are mocked in unit tests via `tests/conftest.py` fixtures
- `-m live` marks tests that require a real `FINMIND_TOKEN`
- V3.4 factor tests validate: correct data requirements, no look-ahead bias, output in [0–1], graceful null handling
- 105+ tests, all green; run before any change to `stock_strategies/factors/` or `context.py`

## Strategy JSON Schema

`strategies/SCHEMA.md` documents the full schema. `strategies/default.json` holds baseline values that all other strategy files inherit from via `loader.py` merge logic.

## Project Status

- **V3.2** (production): daily selection engine, Telegram, Sheets, GitHub Actions — stable
- **V3.3** (deployed): FastAPI backend + Next.js web UI + Gemini AI strategy generator
- **V3.4** (in progress): P1 data layer ✅, P2 factor library ✅, P3 backtest engine + P4–P7 planned
- Design spec: `docs/superpowers/specs/2026-06-13-multi-expert-stock-strategy-design.md` (3575 lines, authoritative)
