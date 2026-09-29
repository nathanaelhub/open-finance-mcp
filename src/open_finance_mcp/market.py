"""Market data: prices and beta (Yahoo Finance chart endpoint), rates (FRED).

Yahoo's chart endpoint is unofficial and keyless; results are labeled as such
so a model citing them can say so. FRED's ``fredgraph.csv`` export is public
and needs no API key.
"""

from __future__ import annotations

import csv
import io
import math
from datetime import UTC, date, datetime

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval={interval}"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (compatible; open-finance-mcp)"}

TREASURY_SERIES = {
    "3M": "DGS3MO", "1Y": "DGS1", "2Y": "DGS2", "5Y": "DGS5",
    "10Y": "DGS10", "20Y": "DGS20", "30Y": "DGS30",
}


def parse_chart(payload: dict) -> dict:
    """Yahoo chart JSON -> {meta, closes: [(date, adjclose)]} (nulls dropped)."""
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"Yahoo chart error: {chart['error'].get('description', chart['error'])}")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise ValueError("Yahoo chart returned no result")
    stamps = result.get("timestamp") or []
    adj = ((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
    if adj is None:
        adj = (result.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
    closes = [
        (datetime.fromtimestamp(t, UTC).date(), float(c))
        for t, c in zip(stamps, adj)
        if c is not None and math.isfinite(c)
    ]
    return {"meta": result.get("meta") or {}, "closes": closes}


def completed_month_closes(closes: list[tuple[date, float]], today: date) -> list[tuple[date, float]]:
    """One close per *completed* calendar month.

    Yahoo's monthly series ends with the in-progress month (and sometimes a
    second, live bar for the same month); a partial month is not a monthly
    return, so anything in the current month is dropped. For duplicate
    months the last bar wins.
    """
    by_month: dict[tuple[int, int], tuple[date, float]] = {}
    for d, c in closes:
        if (d.year, d.month) < (today.year, today.month):
            by_month[(d.year, d.month)] = (d, c)
    return [by_month[k] for k in sorted(by_month)]


def simple_returns(closes: list[tuple[date, float]]) -> dict[tuple[int, int], float]:
    out = {}
    for (_, prev), (d, cur) in zip(closes, closes[1:]):
        out[(d.year, d.month)] = cur / prev - 1.0
    return out


def beta(stock: dict[tuple[int, int], float], market: dict[tuple[int, int], float]) -> tuple[float, int]:
    """OLS beta = cov(r_s, r_m) / var(r_m) over months present in both series."""
    months = sorted(set(stock) & set(market))
    n = len(months)
    if n < 24:
        raise ValueError(f"only {n} overlapping monthly returns; need at least 24 for a beta")
    xs = [market[m] for m in months]
    ys = [stock[m] for m in months]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)
    var = sum((x - mx) ** 2 for x in xs) / (n - 1)
    return cov / var, n


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    """FRED CSV -> [(date, value)], skipping the '.' placeholders for holidays."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2:
        raise ValueError("unexpected FRED CSV format")
    out = []
    for r in rows[1:]:
        if len(r) >= 2 and r[1] not in ("", "."):
            try:
                out.append((r[0], float(r[1])))
            except ValueError:
                continue
    if not out:
        raise ValueError("FRED series has no observations")
    return out
