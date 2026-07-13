"""US stock data via yfinance — same return shapes as data.py TW functions."""

from datetime import datetime, timedelta

import pandas as pd


def get_price_history_us(ticker: str, years: int = 3) -> pd.DataFrame:
    """Fetch US OHLCV history, normalized to TW format (lowercase cols, date string)."""
    try:
        import yfinance as yf
    except ImportError as e:
        raise RuntimeError("yfinance not installed — run `uv add yfinance`") from e

    start = (datetime.now() - timedelta(days=365 * years + 60)).strftime("%Y-%m-%d")
    df = yf.Ticker(ticker).history(start=start, auto_adjust=True)
    if df.empty:
        return pd.DataFrame()

    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]
    # yfinance Date column may be tz-aware; strip tz
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)


def get_fundamental_us(ticker: str) -> dict:
    """Fetch annual EPS (USD) and ROE (%) for the last 3 full years via yfinance.

    Falls back to TTM figures from ticker.info when annual statements are unavailable.
    """
    try:
        import yfinance as yf
    except ImportError as e:
        raise RuntimeError("yfinance not installed — run `uv add yfinance`") from e

    cy = datetime.now().year
    eps: dict[int, float] = {}
    roe: dict[int, float] = {}

    try:
        t = yf.Ticker(ticker)

        # ── Annual income statement + balance sheet ──
        try:
            income = t.income_stmt          # rows = line items, cols = fiscal year dates
            bs = t.balance_sheet
            if income is not None and not income.empty:
                # EPS: try multiple row names across yfinance versions
                for row in ("Diluted EPS", "Basic EPS", "EPS"):
                    if row in income.index:
                        for col in income.columns:
                            y = col.year if hasattr(col, "year") else int(str(col)[:4])
                            val = income.loc[row, col]
                            if pd.notna(val) and cy - 4 <= y < cy:
                                eps[y] = round(float(val), 2)
                        break

                # ROE = Net Income / Stockholders Equity × 100
                if "Net Income" in income.index and bs is not None and not bs.empty:
                    for eq_row in ("Stockholders Equity", "Total Equity Gross Minority Interest",
                                   "Common Stock Equity"):
                        if eq_row in bs.index:
                            for col in income.columns:
                                y = col.year if hasattr(col, "year") else int(str(col)[:4])
                                ni = income.loc["Net Income", col]
                                # Find closest bs column for same fiscal year
                                bs_match = [c for c in bs.columns
                                            if (c.year if hasattr(c, "year") else int(str(c)[:4])) == y]
                                if bs_match:
                                    eq = bs.loc[eq_row, bs_match[0]]
                                    if pd.notna(ni) and pd.notna(eq) and float(eq) > 0 and cy - 4 <= y < cy:
                                        roe[y] = round(float(ni) / float(eq) * 100, 2)
                            break
        except Exception:
            pass  # fall through to info fallback

        # ── Fallback: TTM from ticker.info ──
        if not eps or not roe:
            info = t.info
            if not eps:
                ttm = info.get("trailingEps")
                if ttm is not None:
                    # Duplicate across two years as a proxy for trend
                    eps[cy - 1] = round(float(ttm), 2)
                    eps[cy - 2] = round(float(ttm), 2)
            if not roe:
                ttm_roe = info.get("returnOnEquity")
                if ttm_roe is not None:
                    roe[cy - 1] = round(float(ttm_roe) * 100, 2)
                    roe[cy - 2] = round(float(ttm_roe) * 100, 2)

    except Exception:
        pass

    return {
        "eps": {y: v for y, v in eps.items() if cy - 3 <= y < cy},
        "roe": {y: v for y, v in roe.items() if cy - 3 <= y < cy},
    }
