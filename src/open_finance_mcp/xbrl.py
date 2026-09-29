"""Standardize SEC XBRL "company facts" into citable annual + LTM financials.

Everything here is pure: it takes the parsed JSON from
``data.sec.gov/api/xbrl/companyfacts/CIK##########.json`` and returns plain
dicts, so it can be tested against saved fixtures without the network.

Two facts about the data drive the design:

* Companies tag the same line item differently, and change tags over time
  (Caterpillar's ``NetIncomeLoss`` stops in 2010 and continues as
  ``NetIncomeLossAvailableToCommonStockholdersBasic``). So each metric has a
  priority list of concepts, resolved **per period**: the first concept with a
  value for that period wins, and the concept actually used is reported.
* A 10-K carries prior years as comparatives, and later filings can restate
  them. For each period we take the value from the most recently filed
  report, and cite that filing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Concept priority lists (us-gaap taxonomy). Order matters: first hit wins.
DURATION_CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "RevenuesNetOfInterestExpense",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "net_income": [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
    ],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "d_and_a": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndOther",
        "Depreciation",
    ],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "diluted_eps": ["EarningsPerShareDiluted"],
}

INSTANT_CONCEPTS: dict[str, list[str]] = {
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "short_term_investments": [
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
        "ShortTermInvestments",
    ],
    "total_assets": ["Assets"],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    # Debt components; combined by ``total_debt`` below.
    "ltd_noncurrent": [
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    ],
    "ltd_total": ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"],
    "debt_current": ["DebtCurrent"],
    "ltd_current": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "commercial_paper": ["CommercialPaper"],
    "short_term_borrowings": ["ShortTermBorrowings"],
}

# EPS is USD/share, share counts are "shares"; everything else is USD.
UNITS = {"diluted_shares": "shares", "diluted_eps": "USD/shares"}

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}


class NoUsGaapFacts(ValueError):
    """The filer has no usable us-gaap annual facts (new registrant, IFRS filer, fund...)."""


@dataclass(frozen=True)
class Fact:
    concept: str
    value: float
    start: str | None
    end: str
    form: str
    accession: str
    filed: str
    fy: int | None
    fp: str | None

    @property
    def days(self) -> int | None:
        if self.start is None:
            return None
        return (date.fromisoformat(self.end) - date.fromisoformat(self.start)).days + 1


def filing_url(cik: int, accession: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{accession}-index.htm"
    )


def _facts(gaap: dict, concept: str, unit: str) -> list[Fact]:
    rows = gaap.get(concept, {}).get("units", {}).get(unit, [])
    return [
        Fact(concept, float(r["val"]), r.get("start"), r["end"], r.get("form", ""),
             r["accn"], r.get("filed", ""), r.get("fy"), r.get("fp"))
        for r in rows
        if "val" in r and "accn" in r and "end" in r
    ]


def _unit_for(metric: str) -> str:
    return UNITS.get(metric, "USD")


def _is_annual(f: Fact) -> bool:
    return f.form in ANNUAL_FORMS and f.days is not None and 350 <= f.days <= 380


def _latest_filed(facts: list[Fact]) -> Fact:
    # Ties on the filing date: prefer the later accession for determinism.
    return max(facts, key=lambda f: (f.filed, f.accession))


def annual_periods(gaap: dict) -> list[dict]:
    """Fiscal-year periods, oldest first, keyed off the revenue/net-income facts.

    The fiscal-year label comes from the *original* 10-K for that period (the
    earliest filing that reports it), because comparatives in later 10-Ks
    carry the later filing's ``fy``. Label-by-end-year would be wrong for
    retailers: Home Depot's fiscal 2025 ends on 1 Feb 2026.
    """
    periods: dict[tuple[str, str], list[Fact]] = {}
    for metric in ("revenue", "net_income"):
        for concept in DURATION_CONCEPTS[metric]:
            for f in _facts(gaap, concept, "USD"):
                if _is_annual(f):
                    periods.setdefault((f.start, f.end), []).append(f)
    if not periods:
        raise NoUsGaapFacts("no annual 10-K revenue or net-income facts")

    out = []
    for (start, end), facts in periods.items():
        first = min(facts, key=lambda f: (f.filed, f.accession))
        # Only trust ``fy`` when the first filing is the period's own 10-K,
        # i.e. filed within ~6 months of the period end.
        filed_gap = (date.fromisoformat(first.filed) - date.fromisoformat(end)).days
        fy = first.fy if first.fy and 0 <= filed_gap <= 190 else int(end[:4])
        out.append({"label": f"FY{fy}", "start": start, "end": end})
    out.sort(key=lambda p: p["end"])
    # Overlapping periods (a restated year re-cut with new dates) keep the later one.
    dedup: list[dict] = []
    for p in out:
        if dedup and p["start"] <= dedup[-1]["end"]:
            dedup[-1] = p
        else:
            dedup.append(p)
    return dedup


def _pick(gaap: dict, metric: str, concepts: list[str], match) -> Fact | None:
    """First concept (by priority) with a fact matching ``match``; latest filing wins."""
    for concept in concepts:
        hits = [f for f in _facts(gaap, concept, _unit_for(metric)) if match(f)]
        if hits:
            return _latest_filed(hits)
    return None


def _cell(f: Fact | None) -> dict | None:
    if f is None:
        return None
    return {"value": f.value, "concept": f"us-gaap:{f.concept}", "accession": f.accession}


def _duration_value(gaap, metric, start, end, forms):
    return _pick(gaap, metric, DURATION_CONCEPTS[metric],
                 lambda f: f.start == start and f.end == end and f.form in forms)


def _instant_value(gaap, metric, end, forms):
    return _pick(gaap, metric, INSTANT_CONCEPTS[metric],
                 lambda f: f.start is None and f.end == end and f.form in forms)


def _sum_cells(cells: list[dict | None]) -> float | None:
    vals = [c["value"] for c in cells if c is not None]
    return sum(vals) if vals else None


def total_debt(inst: dict[str, dict | None]) -> tuple[float | None, str]:
    """Combine debt components without double counting. Returns (value, formula).

    ``DebtCurrent`` already includes the current portion of long-term debt,
    commercial paper and short-term borrowings, so those are only summed when
    it is absent. ``LongTermDebt`` includes its current portion, so it is only
    used (minus that portion) when no noncurrent concept exists.
    Operating-lease liabilities are excluded by design.
    """
    if inst.get("ltd_noncurrent"):
        lt, lt_desc = inst["ltd_noncurrent"]["value"], "ltd_noncurrent"
    elif inst.get("ltd_total"):
        lt = inst["ltd_total"]["value"]
        lt_desc = "ltd_total"
        if inst.get("ltd_current"):
            lt -= inst["ltd_current"]["value"]
            lt_desc = "(ltd_total - ltd_current)"
    else:
        lt, lt_desc = None, None

    if inst.get("debt_current"):
        cur, cur_desc = inst["debt_current"]["value"], "debt_current"
    else:
        parts = [k for k in ("ltd_current", "commercial_paper", "short_term_borrowings") if inst.get(k)]
        cur = _sum_cells([inst[k] for k in parts]) if parts else None
        cur_desc = " + ".join(parts) if parts else None

    if lt is None and cur is None:
        return None, "no debt concepts reported"
    formula = " + ".join(d for d in (lt_desc, cur_desc) if d)
    if lt is None:
        formula += " (no long-term debt concept reported: likely incomplete)"
    return (lt or 0.0) + (cur or 0.0), formula


def _derive(row: dict[str, dict | None], inst: dict[str, dict | None]) -> dict[str, dict | None]:
    def v(k, src=row):
        c = src.get(k)
        return None if c is None else c["value"]

    out: dict[str, dict | None] = {}
    oi, da = v("operating_income"), v("d_and_a")
    out["ebitda"] = (
        {"value": oi + da, "formula": "operating_income + d_and_a"}
        if oi is not None and da is not None else None
    )
    cfo, capex = v("operating_cash_flow"), v("capex")
    out["free_cash_flow"] = (
        {"value": cfo - capex, "formula": "operating_cash_flow - capex"}
        if cfo is not None and capex is not None else None
    )
    debt, formula = total_debt(inst)
    out["total_debt"] = None if debt is None else {"value": debt, "formula": formula}
    cash = v("cash", inst)
    if debt is not None and cash is not None:
        sti = v("short_term_investments", inst) or 0.0
        out["net_debt"] = {
            "value": debt - cash - sti,
            "formula": "total_debt - cash - short_term_investments",
        }
    else:
        out["net_debt"] = None
    return out


def _latest_quarter_ytd(gaap: dict, fy_end: str) -> tuple[str, str] | None:
    """(start, end) of the newest 10-Q year-to-date period after ``fy_end``.

    A YTD period starts right after the fiscal year ends (within a week, for
    52/53-week calendars), so 3-month quarterly facts are excluded.
    """
    end_d = date.fromisoformat(fy_end)
    best = None
    for concept in DURATION_CONCEPTS["revenue"] + DURATION_CONCEPTS["net_income"]:
        for f in _facts(gaap, concept, "USD"):
            if f.form in QUARTERLY_FORMS and f.start and 0 < (date.fromisoformat(f.start) - end_d).days <= 7:
                if best is None or f.end > best[1]:
                    best = (f.start, f.end)
    return best


def _ltm_parts(gaap: dict, metric: str, concept: str, last_fy: dict,
               ytd: tuple[str, str]) -> tuple[Fact, Fact, Fact] | None:
    """(FY, current YTD, prior-year YTD) facts for one concept, or None."""
    facts = _facts(gaap, concept, _unit_for(metric))
    length = (date.fromisoformat(ytd[1]) - date.fromisoformat(ytd[0])).days

    def one(pred):
        hits = [f for f in facts if pred(f)]
        return _latest_filed(hits) if hits else None

    fy = one(lambda f: f.form in ANNUAL_FORMS and f.start == last_fy["start"] and f.end == last_fy["end"])
    cur = one(lambda f: f.form in QUARTERLY_FORMS and f.start == ytd[0] and f.end == ytd[1])
    prev = one(lambda f: (f.form in QUARTERLY_FORMS and f.start == last_fy["start"]
                          and abs((date.fromisoformat(f.end) - date.fromisoformat(f.start)).days - length) <= 7))
    return (fy, cur, prev) if fy and cur and prev else None


def standardize(companyfacts: dict, years: int = 5, include_ltm: bool = True) -> dict:
    """Standardized annual (+ optional LTM) financials with per-value citations."""
    cik = int(companyfacts["cik"])
    gaap = companyfacts.get("facts", {}).get("us-gaap")
    if not gaap:
        raise NoUsGaapFacts("filer has no us-gaap facts (IFRS/foreign filer or fund?)")

    periods = annual_periods(gaap)[-years:]
    columns = []
    accessions: set[str] = set()

    for p in periods:
        row = {m: _cell(_duration_value(gaap, m, p["start"], p["end"], ANNUAL_FORMS))
               for m in DURATION_CONCEPTS}
        inst = {m: _cell(_instant_value(gaap, m, p["end"], ANNUAL_FORMS)) for m in INSTANT_CONCEPTS}
        columns.append({**p, "type": "annual", "values": row, "balance_sheet": inst,
                        "derived": _derive(row, inst)})

    if include_ltm and periods:
        ltm = _ltm_column(gaap, periods[-1])
        if ltm:
            columns.append(ltm)

    for col in columns:
        for group in ("values", "balance_sheet"):
            for c in col[group].values():
                if c:
                    accessions.update(c.get("accessions") or [c["accession"]])

    return {
        "cik": cik,
        "entity_name": companyfacts.get("entityName"),
        "currency": "USD",
        "notes": [
            "Values are as most recently reported (restatements included); each cites its filing.",
            "Balance-sheet items are period-end instants. Share counts are weighted diluted.",
            "Derived metrics show their formula. EBITDA is null when operating income is not "
            "reported (common for banks and insurers, where EBITDA is not meaningful).",
        ],
        "periods": columns,
        "filings": {a: {"url": filing_url(cik, a)} for a in sorted(accessions)},
    }


def _ltm_column(gaap: dict, last_fy: dict) -> dict | None:
    ytd = _latest_quarter_ytd(gaap, last_fy["end"])
    if ytd is None:
        return None

    row: dict[str, dict | None] = {}
    for m in DURATION_CONCEPTS:
        if m in ("diluted_shares", "diluted_eps"):
            # Not additive: use the latest quarter's YTD figure as-is.
            f = _duration_value(gaap, m, ytd[0], ytd[1], QUARTERLY_FORMS)
            row[m] = _cell(f)
            continue
        row[m] = None
        # FY + YTD - prior YTD is only valid when one concept covers all three.
        for concept in DURATION_CONCEPTS[m]:
            parts = _ltm_parts(gaap, m, concept, last_fy, ytd)
            if parts:
                fy, cur, prev = parts
                row[m] = {
                    "value": fy.value + cur.value - prev.value,
                    "concept": f"us-gaap:{concept}",
                    "formula": "FY + YTD - prior YTD",
                    "accessions": sorted({fy.accession, cur.accession, prev.accession}),
                }
                break
    inst = {m: _cell(_instant_value(gaap, m, ytd[1], QUARTERLY_FORMS)) for m in INSTANT_CONCEPTS}
    days = (date.fromisoformat(ytd[1]) - date.fromisoformat(ytd[0])).days + 1
    return {
        # Exact span, not "6M": 52/53-week filers (PepsiCo) have 12- and 16-week quarters.
        "label": f"LTM to {ytd[1]}",
        "start": None,
        "end": ytd[1],
        "type": "ltm",
        "ytd": {"start": ytd[0], "end": ytd[1], "days": days},
        "values": row,
        "balance_sheet": inst,
        "derived": _derive(row, inst),
    }


def shares_outstanding(companyfacts: dict) -> dict | None:
    """Latest share count for market cap.

    Prefers the cover-page ``dei:EntityCommonStockSharesOutstanding`` (the most
    recent count, dated weeks after the balance sheet), summed across share
    classes when a filing reports several. Companies that tag the cover page
    only per class (Alphabet) have no undimensioned dei fact in the API, so
    fall back to the balance-sheet ``us-gaap:CommonStockSharesOutstanding``,
    which is already a total across classes.
    """
    facts = companyfacts.get("facts", {})
    cik = int(companyfacts["cik"])
    periodic = ANNUAL_FORMS | QUARTERLY_FORMS

    rows = (facts.get("dei", {}).get("EntityCommonStockSharesOutstanding", {})
            .get("units", {}).get("shares", []))
    rows = [r for r in rows if r.get("form") in periodic]
    if rows:
        latest = max(rows, key=lambda r: (r.get("filed", ""), r["end"]))
        same = [r for r in rows if r["accn"] == latest["accn"] and r["end"] == latest["end"]]
        return {
            "value": sum(float(r["val"]) for r in same),
            "as_of": latest["end"],
            "classes_summed": len(same),
            "concept": "dei:EntityCommonStockSharesOutstanding",
            "accession": latest["accn"],
            "url": filing_url(cik, latest["accn"]),
        }

    rows = (facts.get("us-gaap", {}).get("CommonStockSharesOutstanding", {})
            .get("units", {}).get("shares", []))
    rows = [r for r in rows if r.get("form") in periodic and "start" not in r]
    if not rows:
        return None
    latest = max(rows, key=lambda r: (r["end"], r.get("filed", "")))
    return {
        "value": float(latest["val"]),
        "as_of": latest["end"],
        "classes_summed": None,
        "concept": "us-gaap:CommonStockSharesOutstanding",
        "note": "Cover-page count not available undimensioned; balance-sheet total across all classes.",
        "accession": latest["accn"],
        "url": filing_url(cik, latest["accn"]),
    }
