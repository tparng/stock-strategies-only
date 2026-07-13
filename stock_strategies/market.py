"""大盤狀態濾鏡

台股：抓加權指數 (TAIEX) 的日 K 線，判斷是否站上 20 日均線。
美股：抓 SPY ETF 的日 K 線做相同判斷。
若跌破月線，main.py 會把對應市場的 BUY 訊號降級為 WATCH。
"""

import pandas as pd

from .datasources import get_index_history


def get_market_state(ma_period: int = 20) -> dict:
    """台股大盤狀態（TAIEX 月線）"""
    try:
        df = get_index_history("TAIEX")
        if len(df) < ma_period + 1:
            return {"bullish": True, "close": None, "ma20": None,
                    "note": "⚠️ 大盤資料不足，暫不套用濾鏡"}
        df = df.copy()
        df["ma20"] = df["close"].rolling(ma_period).mean()
        latest = df.iloc[-1]
        close = float(latest["close"]); ma20 = float(latest["ma20"])
        bullish = close > ma20
        pct = (close / ma20 - 1) * 100
        if bullish:
            note = f"🟢 加權 {close:.0f} 站上 {ma_period} 日線 ({pct:+.1f}%)，BUY 訊號照常發出"
        else:
            note = f"🔴 加權 {close:.0f} 跌破 {ma_period} 日線 ({pct:+.1f}%)，BUY 全數降為 WATCH"
        return {"bullish": bullish, "close": close, "ma20": ma20, "note": note}
    except Exception as e:
        return {"bullish": True, "close": None, "ma20": None,
                "note": f"⚠️ 大盤狀態取得失敗（{str(e)[:60]}），暫不套用濾鏡"}


def get_us_market_state(ma_period: int = 20) -> dict:
    """美股大盤狀態（SPY 月線）"""
    try:
        import yfinance as yf
        df = yf.Ticker("SPY").history(period="60d", auto_adjust=True)
        if df.empty or len(df) < ma_period + 1:
            return {"bullish": True, "close": None, "ma20": None,
                    "note": "⚠️ SPY 資料不足，暫不套用美股濾鏡"}
        df = df.copy()
        df["ma20"] = df["Close"].rolling(ma_period).mean()
        close = float(df["Close"].iloc[-1])
        ma20 = float(df["ma20"].iloc[-1])
        bullish = close > ma20
        pct = (close / ma20 - 1) * 100
        if bullish:
            note = f"🟢 SPY {close:.1f} 站上 {ma_period} 日線 ({pct:+.1f}%)，美股 BUY 照常發出"
        else:
            note = f"🔴 SPY {close:.1f} 跌破 {ma_period} 日線 ({pct:+.1f}%)，美股 BUY 降為 WATCH"
        return {"bullish": bullish, "close": close, "ma20": ma20, "note": note}
    except Exception as e:
        return {"bullish": True, "close": None, "ma20": None,
                "note": f"⚠️ 美股大盤狀態取得失敗（{str(e)[:60]}），暫不套用濾鏡"}


def apply_market_filter(results: list[dict], tw_market: dict,
                        us_market: dict | None = None) -> int:
    """依各股市場套用對應大盤濾鏡，BUY → WATCH。回傳被降級數量。"""
    downgraded = 0
    for r in results:
        mkt = r.get("market", "TW")
        market = us_market if (mkt == "US" and us_market) else tw_market
        if not market.get("bullish", True) and r.get("action") == "BUY":
            r["action"] = "WATCH"
            label = "SPY" if mkt == "US" else "大盤"
            r.setdefault("risk_notes", []).append(f"{label} 跌破月線，自動降為 WATCH")
            downgraded += 1
    return downgraded
