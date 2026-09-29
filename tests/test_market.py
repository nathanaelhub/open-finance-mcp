from datetime import date

import pytest

from open_finance_mcp import market
from conftest import load


def test_partial_current_month_is_dropped():
    closes = [(date(2026, 7, 1), 10.0), (date(2026, 8, 1), 11.0),
              (date(2026, 9, 1), 12.0), (date(2026, 9, 29), 12.5)]
    assert market.completed_month_closes(closes, today=date(2026, 9, 29)) == closes[:2]


def test_duplicate_bars_in_a_month_keep_the_last():
    closes = [(date(2026, 7, 1), 10.0), (date(2026, 7, 31), 10.5)]
    assert market.completed_month_closes(closes, today=date(2026, 9, 1)) == [closes[1]]


def test_beta_recovers_a_known_slope():
    mkt = {(2020 + i // 12, i % 12 + 1): ((-1) ** i) * 0.01 * (1 + i % 5) for i in range(36)}
    stock = {k: 0.002 + 1.5 * v for k, v in mkt.items()}
    b, n = market.beta(stock, mkt)
    assert n == 36 and b == pytest.approx(1.5)


def test_beta_refuses_short_histories():
    r = {(2025, m): 0.01 * m for m in range(1, 13)}
    with pytest.raises(ValueError, match="at least 24"):
        market.beta(r, r)


def test_apple_beta_from_real_prices_is_plausible():
    stock = market.parse_chart(load("chart_AAPL.json"))
    index = market.parse_chart(load("chart_GSPC.json"))
    today = stock["closes"][-1][0]
    s = market.completed_month_closes(stock["closes"], today)[-61:]
    m = market.completed_month_closes(index["closes"], today)[-61:]
    b, n = market.beta(market.simple_returns(s), market.simple_returns(m))
    assert n == 60
    assert 0.5 < b < 2.0


def test_chart_errors_are_reported():
    with pytest.raises(ValueError, match="No data found"):
        market.parse_chart({"chart": {"result": None, "error": {"description": "No data found"}}})


def test_fred_csv_skips_holiday_placeholders():
    text = "observation_date,DGS10\n2026-09-24,5.18\n2026-09-25,.\n2026-09-28,5.24\n"
    assert market.parse_fred_csv(text) == [("2026-09-24", 5.18), ("2026-09-28", 5.24)]
