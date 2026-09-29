import pytest

from open_finance_mcp import xbrl
from conftest import load


def rows(cf, concept, unit="USD"):
    return cf["facts"]["us-gaap"][concept]["units"][unit]


def col(result, label):
    return next(p for p in result["periods"] if p["label"] == label)


def fact(val, start, end, accn, filed, form="10-K", fy=None):
    r = {"val": val, "end": end, "accn": accn, "filed": filed, "form": form, "fy": fy, "fp": "FY"}
    if start:
        r["start"] = start
    return r


def companyfacts(gaap, dei=None):
    facts = {"us-gaap": {k: {"units": {"USD": v}} for k, v in gaap.items()}}
    if dei:
        facts["dei"] = dei
    return {"cik": 1, "entityName": "Test Co", "facts": facts}


# ---- real filings ---------------------------------------------------------

def test_apple_fy2024_matches_the_10k(facts):
    r = xbrl.standardize(facts("AAPL"), years=5)
    fy24 = col(r, "FY2024")
    assert (fy24["start"], fy24["end"]) == ("2023-10-01", "2024-09-28")
    assert fy24["values"]["revenue"]["value"] == 391_035_000_000
    assert fy24["values"]["revenue"]["concept"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert fy24["values"]["net_income"]["value"] == 93_736_000_000
    # Apple's FY2024 debt: commercial paper 9.967B + term debt 10.912B current + 85.750B noncurrent.
    debt = fy24["derived"]["total_debt"]
    assert debt["value"] == 106_629_000_000
    assert debt["formula"] == "ltd_noncurrent + ltd_current + commercial_paper"


def test_every_cited_accession_has_a_filing_url(facts):
    r = xbrl.standardize(facts("AAPL"), years=3)
    for p in r["periods"]:
        for group in ("values", "balance_sheet"):
            for cell in p[group].values():
                if cell:
                    for accn in cell.get("accessions") or [cell["accession"]]:
                        assert r["filings"][accn]["url"].endswith(f"{accn}-index.htm")


def test_apple_ltm_is_fy_plus_ytd_minus_prior_ytd(facts):
    cf = facts("AAPL")
    r = xbrl.standardize(cf, years=1)
    ltm = r["periods"][-1]
    assert ltm["type"] == "ltm"
    fy = col(r, "FY2025")
    rev = rows(cf, "RevenueFromContractWithCustomerExcludingAssessedTax")
    ytd_start = "2025-09-28"
    cur = max((x for x in rev if x.get("start") == ytd_start and x["end"] == ltm["end"]), key=lambda x: x["filed"])
    prior = [x for x in rev if x.get("start") == fy["start"] and x["form"] == "10-Q"
             and x["end"] < fy["end"] and x["end"] >= "2025-06-01"]
    expected = fy["values"]["revenue"]["value"] + cur["val"] - max(prior, key=lambda x: x["filed"])["val"]
    assert ltm["values"]["revenue"]["value"] == expected
    assert ltm["label"] == f"LTM to {ltm['end']}"
    assert ltm["ytd"] == {"start": ytd_start, "end": ltm["end"], "days": 273}  # 39 weeks


def test_fiscal_years_follow_the_company_calendar(facts):
    labels = [(p["label"], p["end"]) for p in xbrl.standardize(facts("MSFT"), years=2, include_ltm=False)["periods"]]
    assert labels == [("FY2025", "2025-06-30"), ("FY2026", "2026-06-30")]


def test_bank_uses_long_term_debt_including_current(facts):
    r = xbrl.standardize(facts("JPM"), years=1)
    assert r["periods"][0]["derived"]["total_debt"]["formula"].startswith("ltd_total")
    assert r["periods"][0]["derived"]["ebitda"] is None  # no operating income for a bank


def test_segment_only_debt_is_null_not_zero(facts):
    ltm = xbrl.standardize(facts("CAT"), years=1)["periods"][-1]
    assert ltm["type"] == "ltm"
    assert ltm["derived"]["total_debt"] is None
    assert ltm["derived"]["net_debt"] is None


def test_new_registrant_without_history_raises(facts):
    with pytest.raises(xbrl.NoUsGaapFacts):
        xbrl.standardize(facts("XOM"))


def test_shares_from_cover_page(facts):
    s = xbrl.shares_outstanding(facts("AAPL"))
    assert s["concept"] == "dei:EntityCommonStockSharesOutstanding"
    assert s["classes_summed"] == 1 and s["value"] > 1e10


def test_shares_fall_back_to_balance_sheet_for_per_class_cover_pages(facts):
    s = xbrl.shares_outstanding(facts("GOOGL"))
    assert s["concept"] == "us-gaap:CommonStockSharesOutstanding"
    assert s["classes_summed"] is None and s["value"] > 1e10


# ---- rules, on synthetic facts --------------------------------------------

def test_concept_priority_is_resolved_per_period():
    # Like Caterpillar: NetIncomeLoss stops, a lower-priority concept continues.
    cf = companyfacts({
        "Revenues": [fact(100, "2009-01-01", "2009-12-31", "a-09", "2010-02-20", fy=2009),
                     fact(110, "2010-01-01", "2010-12-31", "a-10", "2011-02-20", fy=2010),
                     fact(120, "2011-01-01", "2011-12-31", "a-11", "2012-02-20", fy=2011)],
        "NetIncomeLoss": [fact(9, "2009-01-01", "2009-12-31", "a-09", "2010-02-20", fy=2009),
                          fact(10, "2010-01-01", "2010-12-31", "a-10", "2011-02-20", fy=2010)],
        "ProfitLoss": [fact(11, "2010-01-01", "2010-12-31", "a-11", "2012-02-20", fy=2011),
                       fact(12, "2011-01-01", "2011-12-31", "a-11", "2012-02-20", fy=2011)],
    })
    ni = [p["values"]["net_income"] for p in xbrl.standardize(cf, include_ltm=False)["periods"]]
    assert [(c["concept"], c["value"]) for c in ni] == [
        ("us-gaap:NetIncomeLoss", 9), ("us-gaap:NetIncomeLoss", 10), ("us-gaap:ProfitLoss", 12)]


def test_restated_value_comes_from_the_latest_filing_and_label_from_the_original():
    cf = companyfacts({"Revenues": [
        fact(100, "2024-02-05", "2025-02-02", "orig", "2025-03-15", fy=2024),
        fact(97, "2024-02-05", "2025-02-02", "restated", "2026-03-14", fy=2025),
    ]})
    p = xbrl.standardize(cf, include_ltm=False)["periods"][0]
    assert p["label"] == "FY2024"  # a retailer year ending Feb 2025 is fiscal 2024
    assert (p["values"]["revenue"]["value"], p["values"]["revenue"]["accession"]) == (97, "restated")


def test_ltm_needs_one_concept_across_fy_and_both_ytds():
    cf = companyfacts({
        "Revenues": [fact(400, "2025-01-01", "2025-12-31", "k", "2026-02-10", fy=2025),
                     fact(90, "2025-01-01", "2025-03-31", "q-prior", "2025-05-01", form="10-Q")],
        "SalesRevenueNet": [fact(110, "2026-01-01", "2026-03-31", "q", "2026-05-01", form="10-Q")],
    })
    ltm = xbrl.standardize(cf)["periods"][-1]
    assert ltm["type"] == "ltm" and ltm["values"]["revenue"] is None

    cf["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        fact(110, "2026-01-01", "2026-03-31", "q", "2026-05-01", form="10-Q"))
    ltm = xbrl.standardize(cf)["periods"][-1]
    assert ltm["values"]["revenue"]["value"] == 400 + 110 - 90


@pytest.mark.parametrize("inst, value, formula", [
    ({"debt_current": 30, "ltd_current": 10, "commercial_paper": 20, "ltd_noncurrent": 100},
     130, "ltd_noncurrent + debt_current"),
    ({"ltd_total": 110, "ltd_current": 10}, 110, "(ltd_total - ltd_current) + ltd_current"),
    ({"short_term_borrowings": 5}, 5, "short_term_borrowings (no long-term debt concept reported: likely incomplete)"),
    ({}, None, "no debt concepts reported"),
])
def test_total_debt_never_double_counts(inst, value, formula):
    cells = {k: {"value": float(v)} for k, v in inst.items()}
    assert xbrl.total_debt(cells) == (value if value is None else float(value), formula)


def test_multi_class_cover_page_is_summed():
    dei = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"val": 300, "end": "2026-07-20", "accn": "x", "filed": "2026-07-25", "form": "10-Q"},
        {"val": 50, "end": "2026-07-20", "accn": "x", "filed": "2026-07-25", "form": "10-Q"},
        {"val": 340, "end": "2026-04-20", "accn": "w", "filed": "2026-04-25", "form": "10-Q"},
    ]}}}
    s = xbrl.shares_outstanding(companyfacts({}, dei=dei))
    assert (s["value"], s["classes_summed"], s["accession"]) == (350, 2, "x")
