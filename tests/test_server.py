"""End-to-end tool calls through an in-process MCP client, with HTTP mocked."""

import json
import re

import httpx
import pytest
import respx
from mcp import Client

from open_finance_mcp.fetch import Fetcher
from open_finance_mcp.server import build_server, enterprise_value
from conftest import FIX, load

UA = "open-finance-mcp tests test@example.com"

# anyio's plugin runs fixture setup, test and teardown in one task, which the
# MCP client's cancel scopes require (pytest-asyncio splits them).
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def result_of(r):
    """Tool output: list returns arrive as structured content, dicts as JSON text."""
    if r.is_error:
        return r.content[0].text
    if r.structured_content is not None:
        return r.structured_content
    return json.loads(r.content[0].text)


def mock_upstream(router: respx.MockRouter) -> None:
    router.get("https://www.sec.gov/files/company_tickers_exchange.json").respond(
        json=load("company_tickers_exchange.json"))
    tickers = load("company_tickers_exchange.json")["data"]

    def by_cik(kind):
        def handler(request):
            cik = int(re.search(r"CIK(\d{10})", str(request.url)).group(1))
            t = next((r[2] for r in tickers if r[0] == cik), None)
            path = FIX / f"{kind}_{t}.json"
            return httpx.Response(200, json=json.loads(path.read_text())) if path.exists() else httpx.Response(404)
        return handler

    router.get(url__regex=r"https://data\.sec\.gov/api/xbrl/companyfacts/.*").mock(side_effect=by_cik("facts"))
    router.get(url__regex=r"https://data\.sec\.gov/submissions/.*").mock(side_effect=by_cik("submissions"))
    router.get(url__regex=r".*/chart/AAPL\?.*").respond(json=load("chart_AAPL.json"))
    router.get(url__regex=r".*/chart/%5EGSPC\?.*|.*/chart/\^GSPC\?.*").respond(json=load("chart_GSPC.json"))
    router.get(url__regex=r"https://fred\.stlouisfed\.org/.*").respond(text=load("fred_DGS10.csv"))
    # Apple's earnings 8-K: its index page, and any document in it (the EX-99.1).
    router.get(url__regex=r"https://www\.sec\.gov/Archives/edgar/data/320193/.*-index\.htm").respond(
        text=load("release_AAPL_index.htm"))
    router.get(url__regex=r"https://www\.sec\.gov/Archives/edgar/data/320193/\d+/[^/]+\.htm").respond(
        text=load("release_AAPL_ex991.htm"))


@pytest.fixture
async def call(tmp_path):
    with respx.mock(assert_all_called=False) as router:
        mock_upstream(router)
        fetcher = Fetcher(cache=tmp_path, sec_user_agent=UA)
        async with Client(build_server(fetcher)) as client:
            async def _call(tool, args=None):
                r = await client.call_tool(tool, args or {})
                return r.is_error, result_of(r)
            yield _call
        await fetcher.aclose()


async def test_tools_are_listed_read_only(tmp_path):
    async with Client(build_server(Fetcher(cache=tmp_path, sec_user_agent=UA))) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == {"lookup_company", "get_financials", "get_filings",
                                       "get_market_data", "get_treasury_yield", "get_comps",
                                       "get_earnings_release"}
    assert all(t.annotations.read_only_hint for t in tools)


async def test_lookup_matches_ticker_then_name(call):
    err, out = await call("lookup_company", {"query": "exxon"})
    assert not err and out["result"][0]["ticker"] == "XOM"


async def test_financials_carry_citations_and_no_warnings_for_a_clean_filer(call):
    err, out = await call("get_financials", {"ticker": "aapl", "years": 2})
    assert not err
    assert out["ticker"] == "AAPL" and out["financial_company"] is False and out["warnings"] == []
    rev = out["periods"][0]["values"]["revenue"]
    assert out["filings"][rev["accession"]]["url"].startswith("https://www.sec.gov/Archives/")


async def test_bank_is_flagged(call):
    err, out = await call("get_financials", {"ticker": "JPM", "years": 1})
    assert not err and out["financial_company"] is True
    assert any("not meaningful" in w for w in out["warnings"])


async def test_lagging_xbrl_api_is_flagged(call):
    err, out = await call("get_financials", {"ticker": "KO", "years": 1})
    assert not err and any("does not include yet" in w and "get_earnings_release" in w
                           for w in out["warnings"])


async def test_new_registrant_explains_itself(call):
    err, msg = await call("get_financials", {"ticker": "XOM"})
    assert err and "predecessor CIK" in msg and "IFRS" not in msg


async def test_unknown_ticker(call):
    err, msg = await call("get_financials", {"ticker": "ZZZZ"})
    assert err and "lookup_company" in msg


async def test_missing_user_agent_is_a_readable_error(tmp_path):
    with respx.mock(assert_all_called=False) as router:
        mock_upstream(router)
        async with Client(build_server(Fetcher(cache=tmp_path, sec_user_agent=""))) as client:
            r = await client.call_tool("lookup_company", {"query": "AAPL"})
    assert r.is_error and "claude plugin configure open-finance" in r.content[0].text


def test_contact_falls_back_to_open_finance_env(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "")  # what the plugin passes when its option is unset
    monkeypatch.setenv("OPEN_FINANCE_SEC_USER_AGENT", UA)
    assert Fetcher()._sec_ua == UA


async def test_filings_filter_by_form(call):
    err, out = await call("get_filings", {"ticker": "AAPL", "forms": ["10-K"], "limit": 2})
    assert not err and out["result"] and {f["form"] for f in out["result"]} == {"10-K"}
    assert out["result"][0]["document_url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/")


async def test_treasury_yield_is_latest_observation(call):
    err, out = await call("get_treasury_yield", {"maturity": "10y"})
    last_date, last_val = load("fred_DGS10.csv").strip().splitlines()[-1].split(",")
    assert not err and (out["as_of"], out["yield_pct"]) == (last_date, float(last_val))
    err, msg = await call("get_treasury_yield", {"maturity": "7Y"})
    assert err and "10Y" in msg


async def test_comps_multiples_follow_from_their_inputs(call):
    err, out = await call("get_comps", {"tickers": ["AAPL", "ZZZZ"]})
    assert not err
    aapl, bad = out["comps"]
    assert "error" in bad
    assert aapl["enterprise_value"] == pytest.approx(aapl["market_cap"] + aapl["net_debt"])
    assert aapl["ev_revenue"] == round(aapl["enterprise_value"] / aapl["revenue"], 2)
    assert aapl["ev_ebitda"] == round(aapl["enterprise_value"] / aapl["ebitda"], 2)
    assert aapl["pe"] == round(aapl["market_cap"] / aapl["net_income"], 2)
    assert out["summary"]["pe"]["n"] == 1


async def test_stdio_entry_point_serves_the_tools(tmp_path):
    """The real transport Claude Code uses: launch the console script over stdio."""
    import os
    import sys

    from mcp import StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "open_finance_mcp.server"],
        env={**os.environ, "SEC_USER_AGENT": UA, "OPEN_FINANCE_MCP_CACHE": str(tmp_path)},
    )
    async with Client(params) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert "get_comps" in names


def _column(debt=None, net_debt=None, cash=None):
    cell = lambda v: None if v is None else {"value": v}  # noqa: E731
    return {"derived": {"total_debt": cell(debt), "net_debt": cell(net_debt)},
            "balance_sheet": {"cash": cell(cash), "short_term_investments": None}}


def test_ev_is_market_cap_plus_net_debt():
    assert enterprise_value(100.0, _column(debt=30, net_debt=20, cash=10), False)["enterprise_value"] == 120.0


def test_ev_is_null_but_explained_when_no_debt_is_reported():
    out = enterprise_value(100.0, _column(cash=10), False)
    assert out["enterprise_value"] is None
    assert out["enterprise_value_if_debt_free"] == 90.0 and "debt-free" in out["notes"][0]


def test_ev_is_not_computed_for_financials():
    out = enterprise_value(100.0, _column(debt=30, net_debt=20, cash=10), True)
    assert out["enterprise_value"] is None and out["enterprise_value_if_debt_free"] is None


async def test_cik_resolves_registrants_without_a_ticker(call):
    err, out = await call("get_financials", {"ticker": "CIK0000320193", "years": 1})
    assert not err and out["cik"] == 320193 and out["ticker"] == "AAPL"
    err, out = await call("get_financials", {"ticker": "320193", "years": 1})
    assert not err and out["cik"] == 320193


async def test_new_registrant_error_points_to_predecessor_cik(call):
    err, msg = await call("get_financials", {"ticker": "XOM"})
    assert err and "CIK0000034088" in msg


async def test_earnings_release_is_the_latest_item_2_02_exhibit(call):
    from open_finance_mcp import release
    latest = release.earnings_8ks(load("submissions_AAPL.json"))[0]
    err, out = await call("get_earnings_release", {"ticker": "AAPL"})
    assert not err
    assert (out["filed"], out["accession"]) == (latest["filingDate"], latest["accessionNumber"])
    assert out["exhibit"]["type"] == "EX-99.1" and out["text"].startswith("Exhibit 99.1")
    assert "unaudited" in out["note"]


async def test_earnings_release_pages_through_the_whole_text(call):
    first = (await call("get_earnings_release", {"ticker": "AAPL", "max_chars": 3000}))[1]
    assert first["next_offset"] and len(first["text"]) <= 3000
    chunks, offset = [first["text"]], first["next_offset"]
    while offset is not None:
        out = (await call("get_earnings_release", {"ticker": "AAPL", "max_chars": 3000, "offset": offset}))[1]
        chunks.append(out["text"])
        offset = out["next_offset"]
    assert len("".join(chunks)) == first["total_chars"]


async def test_earnings_release_errors_are_actionable(call):
    err, msg = await call("get_earnings_release", {"ticker": "AAPL", "exhibit": "EX-99.9"})
    assert err and "available: EX-99.1" in msg
    err, msg = await call("get_earnings_release", {"ticker": "AAPL", "which": 99})
    assert err and "which must be" in msg
