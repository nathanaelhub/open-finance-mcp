---
name: cited-financial-data
description: Use when building comps, a DCF, or any valuation from public-company data with the open-finance MCP tools (SEC EDGAR financials, filings, market data, Treasury yields). Covers which tool supplies each input, how to cite every figure, and which warnings change the analysis.
---

# Cited financial data with open-finance

The `open-finance` tools return a source with every number. Your job is to
keep that source attached all the way into the deliverable.

## Which tool supplies which input

| Input | Tool | Field |
|---|---|---|
| Revenue, EBITDA, net income, FCF (annual + LTM) | `get_financials` | `periods[].values` / `derived` |
| Cash, debt, net debt | `get_financials` | `balance_sheet`, `derived.total_debt`, `derived.net_debt` |
| Price, market cap, shares, beta | `get_market_data` | `price`, `market_cap`, `shares_outstanding`, `beta` |
| Risk-free rate | `get_treasury_yield` (10Y) | `yield_pct` |
| Peer multiples in one call | `get_comps` | `comps[]`, `summary` |
| Filing documents to quote or link | `get_filings` | `document_url` |

Use `lookup_company` first when a name, not a ticker, is given.

## Citation rules

- Every hard-coded input gets a source: the filing URL from `filings[accession]`
  (or `sources` in comps) plus the XBRL concept, e.g.
  "Revenue: us-gaap:Revenues, 10-K accession 0000021344-26-000012 (URL)".
- LTM figures cite all three filings listed in `accessions` and say
  "FY + YTD − prior YTD".
- Derived values (EBITDA, FCF, total debt, net debt) state their `formula`.
- Prices and beta cite "Yahoo Finance chart API (unofficial)" and the as-of
  date; tell the user to verify them before anything is published.

## Warnings that change the analysis

Read `warnings` and `notes` before using a number. Do not drop them silently.

- `financial_company`: banks and insurers. Do not use EV/EBITDA or net debt;
  value on P/E and P/B.
- "does not include yet": the XBRL API lags a newer 10-Q/10-K. Say which
  filing is missing; open it with `get_filings` if the newest quarter matters.
- "Non-operating items … P/E is distorted": weight EV/EBITDA over P/E for that
  company and explain why.
- EV null with `enterprise_value_if_debt_free`: confirm from the balance sheet
  (via the filing) that there is no debt before using the debt-free figure.
- A `null` value means the concept was not reported. Never replace it with 0
  or an estimate without saying so.

## Scope

US-GAAP SEC filers only. Foreign private issuers (20-F/40-F, IFRS) are not
covered; say so rather than improvising figures from memory.
