"""Unit tests for US-specific scoring extensions (evaluate_us.py + RSI in indicators)."""

import pandas as pd
import pytest

from stock_strategies.evaluate_us import (
    earnings_days_ahead,
    us_fundamental_score,
    us_tech_bonus,
)
from stock_strategies.indicators import add_indicators


# ── us_fundamental_score ─────────────────────────────────────────────────────

class TestUsFundamentalScore:
    def _full_fund(self, **overrides) -> dict:
        base = {
            "eps": {2023: 5.0, 2022: 4.2},
            "roe": {2023: 28.0, 2022: 24.0},
            "profit_margin": 0.25,
            "gross_margin": 0.60,
            "eps_growth": 0.30,
            "revenue_growth": 0.22,
            "pe_forward": 22.0,
            "pe_trailing": 25.0,
            "peg": 0.8,
            "debt_to_equity": 20.0,
            "current_ratio": 3.0,
            "next_earnings": None,
        }
        base.update(overrides)
        return base

    def test_high_quality_stock_scores_above_70(self):
        score, signals = us_fundamental_score(self._full_fund())
        assert score >= 70
        assert len(signals) >= 3

    def test_eps_signals_included(self):
        _, signals = us_fundamental_score(self._full_fund())
        assert any("EPS" in s for s in signals)

    def test_revenue_growth_signal_included(self):
        _, signals = us_fundamental_score(self._full_fund())
        assert any("營收" in s or "Revenue" in s or "revenue" in s.lower() for s in signals)

    def test_minimal_existing_interface(self):
        """Only eps and roe keys (as returned by old get_fundamental_us) must not crash."""
        fund = {"eps": {2023: 1.5}, "roe": {2023: 16.0}}
        score, signals = us_fundamental_score(fund)
        assert 0 <= score <= 100

    def test_empty_fund_gives_only_neutral_credits(self):
        # Missing optional fields (P/E, D/E, current ratio) get neutral partial credit
        # so score > 0 is expected; it should be well below the fund_pass threshold (60)
        score, signals = us_fundamental_score({})
        assert 0 <= score < 30
        assert signals == []

    def test_negative_eps_scores_low(self):
        # Only profitability fields provided and all negative → near-zero profitability score
        fund = {"eps": {2023: -2.0, 2022: -1.0}, "roe": {2023: -10.0, 2022: -5.0},
                "profit_margin": -0.05}
        score, _ = us_fundamental_score(fund)
        # Profitability = 0; neutral credits for missing optional fields apply
        assert score < 30

    def test_high_pe_penalised_relative_to_low_pe(self):
        low_pe = us_fundamental_score(self._full_fund(pe_forward=12.0, pe_trailing=None))[0]
        high_pe = us_fundamental_score(self._full_fund(pe_forward=50.0, pe_trailing=None))[0]
        assert low_pe > high_pe

    def test_high_debt_penalised(self):
        low_debt = us_fundamental_score(self._full_fund(debt_to_equity=20.0))[0]
        high_debt = us_fundamental_score(self._full_fund(debt_to_equity=300.0))[0]
        assert low_debt > high_debt

    def test_none_optional_fields_dont_crash(self):
        fund = {
            "eps": {2023: 2.0}, "roe": {2023: 18.0},
            "profit_margin": None, "eps_growth": None, "revenue_growth": None,
            "pe_forward": None, "pe_trailing": None, "peg": None,
            "debt_to_equity": None, "current_ratio": None,
        }
        score, _ = us_fundamental_score(fund)
        assert 0 <= score <= 100

    def test_score_bounded_0_to_100(self):
        # Extremely good stock should not exceed 100
        score, _ = us_fundamental_score(self._full_fund(
            eps_growth=1.0, revenue_growth=0.8, pe_forward=5.0, peg=0.1,
            debt_to_equity=5.0, current_ratio=5.0, profit_margin=0.5,
        ))
        assert 0 <= score <= 100


# ── us_tech_bonus ─────────────────────────────────────────────────────────────

class TestUsTechBonus:
    def test_healthy_rsi_zone_gives_bonus(self):
        bonus, signals = us_tech_bonus(rsi=55.0, stock_ret_20d=8.0, spy_ret_20d=3.0)
        assert bonus > 0
        assert any("RSI" in s for s in signals)

    def test_overbought_rsi_gives_no_rsi_bonus(self):
        bonus_ob, _ = us_tech_bonus(rsi=80.0, stock_ret_20d=0.0, spy_ret_20d=0.0)
        bonus_ok, _ = us_tech_bonus(rsi=55.0, stock_ret_20d=0.0, spy_ret_20d=0.0)
        assert bonus_ok > bonus_ob

    def test_outperforming_spy_adds_to_bonus(self):
        bonus_out, _ = us_tech_bonus(rsi=55.0, stock_ret_20d=15.0, spy_ret_20d=3.0)
        bonus_under, _ = us_tech_bonus(rsi=55.0, stock_ret_20d=0.0, spy_ret_20d=3.0)
        assert bonus_out > bonus_under

    def test_strong_outperformance_vs_spy_signal(self):
        _, signals = us_tech_bonus(rsi=55.0, stock_ret_20d=18.0, spy_ret_20d=3.0)
        assert any("SPY" in s for s in signals)

    def test_none_inputs_no_crash(self):
        bonus, signals = us_tech_bonus(rsi=None, stock_ret_20d=None, spy_ret_20d=None)
        assert isinstance(bonus, int)
        assert isinstance(signals, list)

    def test_nan_rsi_treated_as_missing(self):
        bonus_nan, _ = us_tech_bonus(rsi=float("nan"), stock_ret_20d=0.0, spy_ret_20d=0.0)
        bonus_none, _ = us_tech_bonus(rsi=None, stock_ret_20d=0.0, spy_ret_20d=0.0)
        assert bonus_nan == bonus_none

    def test_bonus_non_negative(self):
        bonus, _ = us_tech_bonus(rsi=80.0, stock_ret_20d=-10.0, spy_ret_20d=5.0)
        assert bonus >= 0


# ── earnings_days_ahead ───────────────────────────────────────────────────────

class TestEarningsDaysAhead:
    def test_future_5_days(self):
        from datetime import datetime, timedelta
        future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        assert earnings_days_ahead(future) == 5

    def test_past_date_returns_none(self):
        from datetime import datetime, timedelta
        past = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        assert earnings_days_ahead(past) is None

    def test_none_input_returns_none(self):
        assert earnings_days_ahead(None) is None

    def test_empty_string_returns_none(self):
        assert earnings_days_ahead("") is None

    def test_today_returns_zero(self):
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        result = earnings_days_ahead(today)
        assert result == 0

    def test_bad_format_returns_none(self):
        assert earnings_days_ahead("not-a-date") is None


# ── RSI in indicators ─────────────────────────────────────────────────────────

class TestRsiInIndicators:
    def _price_df(self, n: int = 40, trend: float = 0.5) -> pd.DataFrame:
        return pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n),
            "open": [100.0] * n,
            "high": [105.0] * n,
            "low": [95.0] * n,
            "close": [100.0 + i * trend for i in range(n)],
            "volume": [1000] * n,
        })

    def test_rsi_column_added(self):
        df = add_indicators(self._price_df())
        assert "rsi" in df.columns

    def test_rsi_not_null_after_warmup(self):
        df = add_indicators(self._price_df(n=40))
        # RSI needs ~14 bars to warm up; last value should be non-null
        assert pd.notna(df["rsi"].iloc[-1])

    def test_uptrend_rsi_above_50(self):
        df = add_indicators(self._price_df(trend=0.5))
        assert df["rsi"].iloc[-1] > 50

    def test_downtrend_rsi_below_50(self):
        df = add_indicators(self._price_df(trend=-0.5))
        assert df["rsi"].iloc[-1] < 50

    def test_rsi_bounded_0_to_100(self):
        df = add_indicators(self._price_df(n=50))
        valid = df["rsi"].dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_existing_indicator_columns_still_present(self):
        """RSI addition must not remove any existing columns."""
        df = add_indicators(self._price_df())
        for col in ["ma5", "ma20", "ma60", "bb_upper", "bb_lower", "k", "d",
                    "macd_hist", "atr"]:
            assert col in df.columns, f"Missing column: {col}"
