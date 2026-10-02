"""Refresh tests/fixtures from the live APIs, trimmed to what the code reads.

    SEC_USER_AGENT="Name you@example.com" uv run python scripts/make_fixtures.py

Fixtures are real filings, cut down to the concepts in xbrl.py and to recent
periods so the test suite stays small and runs offline.
"""

import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from open_finance_mcp import xbrl  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
UA = {"User-Agent": os.environ["SEC_USER_AGENT"]}
# AAPL/MSFT: clean filers. CAT: net-income tag change + segment-only 10-Q debt.
# JPM: bank. KO: XBRL API lagging the latest 10-Q. GOOGL: per-class cover page.
# XOM: new holding-company registrant with no history.
TICKERS = ["AAPL", "MSFT", "CAT", "JPM", "KO", "GOOGL", "XOM"]
SINCE = "2021-01-01"
KEEP = ({c for cs in xbrl.DURATION_CONCEPTS.values() for c in cs}
        | {c for cs in xbrl.INSTANT_CONCEPTS.values() for c in cs}
        | {"CommonStockSharesOutstanding"})


def get(url, headers=UA):
    time.sleep(0.15)
    r = httpx.get(url, headers=headers, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r


def trim_facts(cf):
    facts = {}
    for ns, keep in (("us-gaap", KEEP), ("dei", {"EntityCommonStockSharesOutstanding"})):
        src = cf.get("facts", {}).get(ns, {})
        out = {}
        for concept in sorted(keep & set(src)):
            units = {u: [r for r in rows if r["end"] >= SINCE] for u, rows in src[concept]["units"].items()}
            units = {u: rows for u, rows in units.items() if rows}
            if units:
                out[concept] = {"units": units}
        if out:
            facts[ns] = out
    return {"cik": cf["cik"], "entityName": cf["entityName"], "facts": facts}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tick = get("https://www.sec.gov/files/company_tickers_exchange.json").json()
    rows = [r for r in tick["data"] if r[2] in TICKERS + ["PEP", "NPT"]]
    (OUT / "company_tickers_exchange.json").write_text(json.dumps({"fields": tick["fields"], "data": rows}))
    for t in TICKERS:
        cik = next(r[0] for r in rows if r[2] == t)
        cf = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()
        (OUT / f"facts_{t}.json").write_text(json.dumps(trim_facts(cf)))
        sub = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
        # Keep every periodic filing and 8-K plus the 20 newest of anything else
        # (Form 4s dominate large-cap filing lists).
        r = sub["filings"]["recent"]
        idx = [i for i, f in enumerate(r["form"]) if i < 20 or f in ("10-K", "10-Q", "10-K/A", "10-Q/A", "8-K")]
        recent = {k: [v[i] for i in idx] for k, v in r.items()}
        keep = {k: sub.get(k) for k in ("cik", "name", "tickers", "exchanges", "sic", "sicDescription", "fiscalYearEnd")}
        (OUT / f"submissions_{t}.json").write_text(json.dumps({**keep, "filings": {"recent": recent}}))
    # Apple's latest earnings 8-K: the filing index page and its EX-99.1.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from open_finance_mcp import release
    sub = json.loads((OUT / "submissions_AAPL.json").read_text())
    accn = release.earnings_8ks(sub)[0]["accessionNumber"]
    index = get(xbrl.filing_url(320193, accn)).text
    (OUT / "release_AAPL_index.htm").write_text(index)
    ex = release.release_exhibits(release.filing_documents(index))[0]
    (OUT / "release_AAPL_ex991.htm").write_text(get(ex["url"]).text)
    for sym, name in (("AAPL", "AAPL"), ("^GSPC", "GSPC")):
        r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=6y&interval=1mo",
                {"User-Agent": "Mozilla/5.0"})
        (OUT / f"chart_{name}.json").write_text(r.text)
    csv = get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", {}).text.splitlines()
    (OUT / "fred_DGS10.csv").write_text("\n".join(csv[:1] + csv[-30:]) + "\n")
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
