"""US-specific scoring extensions used by evaluate.py.

Keeps the shared TW scoring path (tech_score_at, backtest, binary fund gate)
completely unchanged. The functions here are called only when `is_us_stock()`
returns True.
"""

from __future__ import annotations
from datetime import datetime

import pandas as pd


# ── Fundamental score ────────────────────────────────────────────────────────

def us_fundamental_score(fund: dict) -> tuple[float, list[str]]:
    """Multi-factor graduated fundamental score (0–100) for US stocks.

    Dimensions and max points:
      Profitability  — 30 pts : EPS level + ROE + net margin
      Growth         — 25 pts : EPS YoY growth + revenue growth
      Valuation      — 20 pts : forward/trailing P/E + PEG ratio
      Financial health — 25 pts : debt/equity + current ratio

    Missing fields score 0 for that sub-dimension; no exception is raised.
    Returns (score, signals) where signals are human-readable passing criteria.
    """
    score = 0.0
    signals: list[str] = []

    # ── Profitability (30 pts) ────────────────────────────────────────────────
    eps_vals = [v for v in fund.get("eps", {}).values() if v is not None]
    roe_vals = [v for v in fund.get("roe", {}).values() if v is not None]

    if eps_vals:
        eps_min = min(eps_vals)
        if eps_min > 3.0:
            score += 10; signals.append(f"EPS ${eps_min:.2f}")
        elif eps_min > 1.0:
            score += 7; signals.append(f"EPS ${eps_min:.2f}")
        elif eps_min > 0:
            score += 3

    margin = fund.get("profit_margin")
    if margin is not None:
        if margin > 0.20:
            score += 12; signals.append(f"淨利率 {margin*100:.0f}%")
        elif margin > 0.10:
            score += 8
        elif margin > 0.03:
            score += 4

    if roe_vals:
        roe_min = min(roe_vals)
        if roe_min > 25:
            score += 8; signals.append(f"ROE {roe_min:.0f}%")
        elif roe_min > 15:
            score += 6; signals.append(f"ROE {roe_min:.0f}%")
        elif roe_min > 8:
            score += 3
        elif roe_min > 0:
            score += 1

    # ── Growth (25 pts) ──────────────────────────────────────────────────────
    eps_g = fund.get("eps_growth")
    if eps_g is not None:
        if eps_g > 0.25:
            score += 15; signals.append(f"EPS年增 +{eps_g*100:.0f}%")
        elif eps_g > 0.10:
            score += 10; signals.append(f"EPS年增 +{eps_g*100:.0f}%")
        elif eps_g > 0:
            score += 5

    rev_g = fund.get("revenue_growth")
    if rev_g is not None:
        if rev_g > 0.20:
            score += 10; signals.append(f"營收年增 +{rev_g*100:.0f}%")
        elif rev_g > 0.05:
            score += 6
        elif rev_g > 0:
            score += 2

    # ── Valuation (20 pts) ───────────────────────────────────────────────────
    pe_fwd = fund.get("pe_forward")
    pe_trail = fund.get("pe_trailing")
    pe = pe_fwd if (pe_fwd and pe_fwd > 0) else pe_trail
    if pe and pe > 0:
        if pe < 15:
            score += 15; signals.append(f"本益比 {pe:.1f}")
        elif pe < 25:
            score += 10
        elif pe < 40:
            score += 5
        # > 40: growth premium, 0 pts but not penalised
    else:
        score += 7  # no P/E data → neutral, partial credit

    peg = fund.get("peg")
    if peg and 0 < peg < 1.0:
        score += 5; signals.append(f"PEG {peg:.2f}")
    elif peg and peg < 2.0:
        score += 2

    # ── Financial health (25 pts) ────────────────────────────────────────────
    # yfinance debtToEquity is reported as ratio × 100 (e.g. 25 ≈ D/E 0.25x)
    de = fund.get("debt_to_equity")
    if de is not None:
        if de < 30:       # D/E < 0.3x — very low leverage
            score += 13
        elif de < 100:    # D/E < 1.0x — manageable
            score += 9
        elif de < 200:    # D/E < 2.0x — elevated
            score += 4
    else:
        score += 5  # unknown → neutral

    cr = fund.get("current_ratio")
    if cr is not None:
        if cr > 2.0:
            score += 12
        elif cr > 1.5:
            score += 8
        elif cr > 1.0:
            score += 4
    else:
        score += 5  # unknown → neutral

    return min(100.0, round(score, 1)), signals


# ── Technical bonus ──────────────────────────────────────────────────────────

def us_tech_bonus(
    rsi: float | None,
    stock_ret_20d: float | None,
    spy_ret_20d: float | None,
) -> tuple[int, list[str]]:
    """RSI + relative-strength-vs-SPY bonus on top of base tech_score_at().

    Max +20 pts:  RSI zone (0–12) + relative strength (0–8).
    The caller is responsible for adding overbought / RS-lagging risk notes.
    """
    bonus = 0
    signals: list[str] = []

    # RSI (0–12 pts) — rewards momentum without overheating
    if rsi is not None and pd.notna(rsi):
        rsi_f = float(rsi)
        if 40 <= rsi_f <= 65:
            bonus += 12; signals.append(f"RSI {rsi_f:.0f} 健康區")
        elif 65 < rsi_f <= 75:
            bonus += 6; signals.append(f"RSI {rsi_f:.0f} 偏熱")
        elif rsi_f < 40:
            bonus += 4  # weak / oversold — partial credit, no label

    # Relative strength vs SPY (0–8 pts)
    if stock_ret_20d is not None and spy_ret_20d is not None:
        rs = stock_ret_20d - spy_ret_20d
        if rs > 10:
            bonus += 8; signals.append(f"強於SPY +{rs:.1f}%")
        elif rs > 5:
            bonus += 5; signals.append(f"強於SPY +{rs:.1f}%")
        elif rs > 0:
            bonus += 2

    return bonus, signals


# ── Earnings risk ─────────────────────────────────────────────────────────────

def earnings_days_ahead(next_earnings: str | None) -> int | None:
    """Calendar days from today to next_earnings date string (YYYY-MM-DD).

    Returns None if the date is unavailable or already past.
    """
    if not next_earnings:
        return None
    try:
        ed = datetime.strptime(next_earnings, "%Y-%m-%d").date()
        today = datetime.now().date()
        delta = (ed - today).days
        return delta if delta >= 0 else None
    except (ValueError, TypeError):
        return None
