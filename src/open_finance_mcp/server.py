"""MCP server: free, citable financial data for comps and DCF work.

Tools return JSON with a source for every number (SEC filing accession and
URL, XBRL concept, or the market-data endpoint), so a model can footnote its
work the way the financial-services ``/comps`` and ``/dcf`` skills require.
"""

from __future__ import annotations

import re
import statistics
from datetime import date

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import market, xbrl
from .fetch import ConfigError, Fetcher, UpstreamError

TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

DAY = 86_400
TTL_TICKERS = 7 * DAY
TTL_FACTS = DAY
TTL_SUBMISSIONS = 6 * 3600
TTL_MARKET = 15 * 60
TTL_FRED = 6 * 3600

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True)

INSTRUCTIONS = """\
Free financial data with citations: SEC EDGAR XBRL financials and filings,
FRED Treasury yields, and Yahoo Finance prices/beta (unofficial source).
Cite the accession/URL returned with each figure. EBITDA and net debt are
derived and show their formula. For banks and insurers (flagged
`financial_company`), EV-based multiples are not meaningful. US-GAAP filers
only; foreign private issuers filing IFRS 20-F/40-F are not supported."""


def _is_financial(sic: str | None) -> bool:
    # 6000-6399: banks, credit, brokers, insurance carriers; 6700s: holding/investment offices.
    try:
        code = int(sic or 0)
    except ValueError:
        return False
    return 6000 <= code <= 6399 or 6700 <= code <= 6799


class Data:
    """Upstream access used by the tools (separate so tests can mock HTTP)."""

    def __init__(self, fetcher: Fetcher):
        self.f = fetcher

    async def companies(self) -> list[dict]:
        payload = await self.f.sec_json(TICKERS_URL, TTL_TICKERS)
        fields = payload["fields"]
        return [dict(zip(fields, row)) for row in payload["data"]]

    async def resolve(self, ticker: str) -> dict:
        """A ticker, or a CIK ("CIK0000034088" or "34088") for registrants without one.

        SEC's ticker list only covers current tickers, so a predecessor company
        (Exxon Mobil Corp after its ticker moved to a new holding company) is
        reachable only by CIK.
        """
        raw = ticker.strip().upper()
        m = re.fullmatch(r"(?:CIK)?0*(\d{1,10})", raw)
        if m:
            cik = int(m.group(1))
            sub = await self.submissions(cik)
            tickers = sub.get("tickers") or []
            exchanges = sub.get("exchanges") or []
            return {"cik": cik, "name": sub.get("name"), "ticker": tickers[0] if tickers else f"CIK{cik:010d}",
                    "exchange": exchanges[0] if exchanges else None}
        want = raw.replace(".", "-")
        for c in await self.companies():
            if str(c["ticker"]).upper() == want:
                return c
        raise ToolError(f"Unknown ticker {ticker!r}. Use lookup_company to search by name, "
                        "or pass a CIK such as 'CIK0000320193'.")

    async def facts(self, cik: int) -> dict:
        return await self.f.sec_json(FACTS_URL.format(cik=cik), TTL_FACTS)

    async def submissions(self, cik: int) -> dict:
        return await self.f.sec_json(SUBMISSIONS_URL.format(cik=cik), TTL_SUBMISSIONS)

    async def chart(self, symbol: str, range_: str, interval: str) -> dict:
        url = market.YAHOO_CHART.format(symbol=symbol, range=range_, interval=interval)
        return market.parse_chart(await self.f.get_json(url, TTL_MARKET, market.BROWSER_UA))

    async def fred(self, series: str) -> list[tuple[str, float]]:
        text = await self.f.get_text(market.FRED_CSV.format(series=series), TTL_FRED)
        return market.parse_fred_csv(text)


def _recent_filings(sub: dict) -> list[dict]:
    r = sub.get("filings", {}).get("recent", {})
    keys = ("form", "filingDate", "reportDate", "accessionNumber", "primaryDocument", "primaryDocDescription")
    return [dict(zip(keys, vals)) for vals in zip(*(r.get(k, []) for k in keys))]


def staleness_warning(sub: dict, cited_accessions: set[str]) -> str | None:
    """Warn when EDGAR lists a newer 10-K/10-Q than the XBRL API has processed."""
    periodic = [f for f in _recent_filings(sub) if f["form"] in ("10-K", "10-Q", "10-K/A", "10-Q/A")]
    if not periodic:
        return None
    newest = max(periodic, key=lambda f: f["filingDate"])
    if newest["accessionNumber"] in cited_accessions:
        return None
    return (f"EDGAR lists a {newest['form']} filed {newest['filingDate']} (period {newest['reportDate']}) "
            f"that the XBRL company-facts API does not include yet; figures stop at the prior filing.")


def enterprise_value(market_cap: float | None, column: dict, financial: bool) -> dict:
    """EV = market cap + net debt, with an explicit answer when debt is unknown.

    XBRL has no "zero debt" fact: a debt-free company (Monster Beverage) simply
    reports no debt concepts, which looks the same as debt tagged only by
    segment. So EV stays null, and a separately labeled debt-free figure is
    offered for the model to use only after checking the balance sheet.
    """
    out = {"enterprise_value": None, "enterprise_value_if_debt_free": None, "notes": []}
    if market_cap is None or financial:
        return out
    net_debt = (column["derived"].get("net_debt") or {}).get("value")
    if net_debt is not None:
        out["enterprise_value"] = market_cap + net_debt
        return out
    bs = column["balance_sheet"]
    cash = (bs.get("cash") or {}).get("value")
    if column["derived"].get("total_debt") is None and cash is not None:
        sti = (bs.get("short_term_investments") or {}).get("value") or 0.0
        out["enterprise_value_if_debt_free"] = market_cap - cash - sti
        out["notes"].append(
            "No debt concepts in XBRL, so EV and EV multiples are null. If the balance sheet "
            "confirms the company is debt-free, use enterprise_value_if_debt_free "
            "(market cap - cash - short-term investments).")
    return out


def build_server(fetcher: Fetcher | None = None) -> MCPServer:
    data = Data(fetcher or Fetcher())
    mcp = MCPServer("open-finance", instructions=INSTRUCTIONS, version="0.1.1")

    async def guarded(coro):
        try:
            return await coro
        except ToolError:
            raise
        except ConfigError as e:
            raise ToolError(f"Configuration error: {e}") from e
        except UpstreamError as e:
            raise ToolError(f"Upstream data source failed: {e}") from e
        except xbrl.NoUsGaapFacts as e:
            raise ToolError(str(e)) from e
        except ValueError as e:
            raise ToolError(str(e)) from e

    async def _financials(ticker: str, years: int, include_ltm: bool) -> dict:
        co = await data.resolve(ticker)
        cik = int(co["cik"])
        facts = await data.facts(cik)
        try:
            out = xbrl.standardize(facts, years=years, include_ltm=include_ltm)
        except xbrl.NoUsGaapFacts as e:
            raise ToolError(
                f"{co['name']} (CIK {cik}) has no usable US-GAAP annual financials: {e}. "
                "If you know a predecessor registrant's CIK, call again with it as the ticker "
                "(e.g. 'CIK0000034088'); otherwise do not substitute figures from memory."
            ) from e
        sub = await data.submissions(cik)
        warnings = []
        if (w := staleness_warning(sub, set(out["filings"]))):
            warnings.append(w)
        if _is_financial(sub.get("sic")):
            warnings.append(f"financial_company (SIC {sub.get('sic')} {sub.get('sicDescription')}): "
                            "EBITDA, net debt and EV multiples are not meaningful; use P/E and P/B.")
        out.update(ticker=co["ticker"], exchange=co.get("exchange"), sic=sub.get("sic"),
                   fiscal_year_end=sub.get("fiscalYearEnd"), warnings=warnings,
                   financial_company=_is_financial(sub.get("sic")))
        return out

    async def _market(ticker: str) -> dict:
        co = await data.resolve(ticker)
        if co["ticker"].startswith("CIK"):
            raise ToolError(f"{co['name']} has no current ticker, so there is no market price.")
        symbol = co["ticker"].replace(".", "-")
        stock = await data.chart(symbol, "6y", "1mo")
        meta = stock["meta"]
        price = meta.get("regularMarketPrice")
        if price is None:
            raise ToolError(f"No price available for {symbol}")
        as_of = meta.get("regularMarketTime")
        facts = await data.facts(int(co["cik"]))
        shares = xbrl.shares_outstanding(facts)

        out: dict = {
            "ticker": co["ticker"],
            "name": co["name"],
            "price": price,
            "currency": meta.get("currency"),
            "price_as_of": date.fromtimestamp(as_of).isoformat() if as_of else None,
            "price_source": "Yahoo Finance chart API (unofficial; verify before publishing)",
            "shares_outstanding": shares,
            "market_cap": price * shares["value"] if shares else None,
            "notes": [],
        }
        if shares and shares["classes_summed"] != 1:  # several classes, or unknown (fallback)
            out["notes"].append(
                f"Share count may cover several share classes but is priced at {symbol}; "
                "other classes can trade at a different price.")
        if meta.get("currency") not in (None, "USD"):
            out["notes"].append("Price is not in USD but SEC financials are; convert before use.")

        try:
            index = await data.chart("^GSPC", "6y", "1mo")
            today = date.today()
            s = market.completed_month_closes(stock["closes"], today)[-61:]
            m = market.completed_month_closes(index["closes"], today)[-61:]
            b, n = market.beta(market.simple_returns(s), market.simple_returns(m))
            out["beta"] = {
                "value": round(b, 3),
                "method": f"OLS on {n} completed monthly returns vs S&P 500 (^GSPC), price-only index",
                "window_end": s[-1][0].isoformat(),
            }
        except (ValueError, UpstreamError) as e:
            out["beta"] = None
            out["notes"].append(f"Beta unavailable: {e}")
        return out

    @mcp.tool(annotations=READ_ONLY)
    async def lookup_company(query: str, limit: int = 10) -> list[dict]:
        """Find SEC registrants by ticker or name. Returns ticker, name, CIK and exchange."""
        async def run():
            q = query.strip().upper()
            if not q:
                raise ToolError("query is empty")
            rows = await data.companies()
            exact = [c for c in rows if str(c["ticker"]).upper() == q]
            by_name = [c for c in rows if q in str(c["name"]).upper() and c not in exact]
            return [{"ticker": c["ticker"], "name": c["name"], "cik": c["cik"], "exchange": c.get("exchange")}
                    for c in (exact + by_name)[:max(1, min(limit, 50))]]
        return await guarded(run())

    @mcp.tool(annotations=READ_ONLY)
    async def get_financials(ticker: str, years: int = 5, include_ltm: bool = True) -> dict:
        """Standardized annual (and LTM) financials from SEC XBRL filings.

        `ticker` may also be a CIK ("CIK0000034088"), for registrants with no
        current ticker such as a predecessor company.

        Income statement, cash flow and balance-sheet items plus derived EBITDA,
        free cash flow, total debt and net debt. Every value carries its XBRL
        concept and filing accession; `filings` maps accessions to URLs.
        """
        return await guarded(_financials(ticker, max(1, min(years, 15)), include_ltm))

    @mcp.tool(annotations=READ_ONLY)
    async def get_filings(ticker: str, forms: list[str] | None = None, limit: int = 10) -> list[dict]:
        """Recent SEC filings with document links. `forms` filters, e.g. ["10-K", "10-Q", "8-K"]."""
        async def run():
            co = await data.resolve(ticker)
            cik = int(co["cik"])
            wanted = {f.upper() for f in forms} if forms else None
            out = []
            for f in _recent_filings(await data.submissions(cik)):
                if wanted and f["form"].upper() not in wanted:
                    continue
                folder = f"https://www.sec.gov/Archives/edgar/data/{cik}/{f['accessionNumber'].replace('-', '')}"
                out.append({
                    "form": f["form"], "filed": f["filingDate"], "period": f["reportDate"] or None,
                    "accession": f["accessionNumber"], "description": f["primaryDocDescription"] or None,
                    "document_url": f"{folder}/{f['primaryDocument']}" if f["primaryDocument"] else None,
                    "index_url": xbrl.filing_url(cik, f["accessionNumber"]),
                })
                if len(out) >= max(1, min(limit, 100)):
                    break
            return out
        return await guarded(run())

    @mcp.tool(annotations=READ_ONLY)
    async def get_market_data(ticker: str) -> dict:
        """Share price, SEC cover-page shares outstanding, market cap and 5-year monthly beta."""
        return await guarded(_market(ticker))

    @mcp.tool(annotations=READ_ONLY)
    async def get_treasury_yield(maturity: str = "10Y") -> dict:
        """Latest US Treasury constant-maturity yield from FRED (percent). 10Y is the usual DCF risk-free rate."""
        async def run():
            key = maturity.strip().upper()
            series = market.TREASURY_SERIES.get(key)
            if not series:
                raise ToolError(f"maturity must be one of {', '.join(market.TREASURY_SERIES)}")
            obs = await data.fred(series)
            d, v = obs[-1]
            return {"maturity": key, "yield_pct": v, "as_of": d, "series": series,
                    "source": f"FRED {series}, https://fred.stlouisfed.org/series/{series}"}
        return await guarded(run())

    @mcp.tool(annotations=READ_ONLY)
    async def get_comps(tickers: list[str]) -> dict:
        """Trading comparables: market cap, EV, LTM revenue/EBITDA/net income, EV/Revenue, EV/EBITDA, P/E.

        EV = market cap + latest net debt. Multiples are null (with a reason)
        when an input is missing, negative, or not meaningful (financials).
        """
        async def run():
            if not tickers or len(tickers) > 15:
                raise ToolError("pass 1-15 tickers")
            rows = []
            for t in tickers:
                try:
                    rows.append(await _comp_row(t))
                except ToolError as e:
                    rows.append({"ticker": t.upper(), "error": str(e)})
            summary = {}
            for k in ("ev_revenue", "ev_ebitda", "pe"):
                vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
                summary[k] = ({"median": round(statistics.median(vals), 2),
                               "mean": round(statistics.fmean(vals), 2), "n": len(vals)} if vals else None)
            return {"comps": rows, "summary": summary,
                    "method": "LTM where a 10-Q follows the last 10-K, else latest fiscal year. "
                              "EV = market cap + net debt (total debt - cash - short-term investments)."}
        return await guarded(run())

    async def _comp_row(ticker: str) -> dict:
        fin = await guarded(_financials(ticker, 1, True))
        mkt = await guarded(_market(ticker))
        col = fin["periods"][-1]
        v, d = col["values"], col["derived"]
        val = lambda c: None if c is None else c["value"]  # noqa: E731
        rev, ebitda, ni = val(v.get("revenue")), val(d.get("ebitda")), val(v.get("net_income"))
        mcap, net_debt = mkt["market_cap"], val(d.get("net_debt"))
        fin_co = fin["financial_company"]
        evs = enterprise_value(mcap, col, fin_co)
        ev = evs["enterprise_value"]
        notes = list(fin["warnings"]) + mkt["notes"] + evs["notes"]
        oi, pretax = val(v.get("operating_income")), val(v.get("pretax_income"))
        if oi and pretax is not None and oi > 0 and abs(pretax - oi) > 0.25 * oi:
            notes.append(
                f"Non-operating items of {(pretax - oi) / 1e9:+.1f}B (pretax - operating income) "
                f"exceed 25% of operating income; P/E is distorted, prefer EV/EBITDA.")

        def ratio(num, den, name):
            if num is None or den is None:
                return None
            if den <= 0:
                notes.append(f"{name} not meaningful (denominator <= 0)")
                return None
            return round(num / den, 2)

        return {
            "ticker": fin["ticker"], "name": fin["entity_name"], "period": col["label"],
            "price": mkt["price"], "market_cap": mcap, "net_debt": net_debt, "enterprise_value": ev,
            "enterprise_value_if_debt_free": evs["enterprise_value_if_debt_free"],
            "revenue": rev, "ebitda": ebitda, "net_income": ni,
            "ev_revenue": ratio(ev, rev, "EV/Revenue"),
            "ev_ebitda": ratio(ev, ebitda, "EV/EBITDA"),
            "pe": ratio(mcap, ni, "P/E"),
            "beta": (mkt.get("beta") or {}).get("value"),
            "financial_company": fin_co,
            "notes": notes,
            "sources": fin["filings"],
        }

    return mcp


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
