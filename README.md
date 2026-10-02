# open-finance-mcp

An MCP server that gives Claude **free, citable** financial data for comps and
DCF work: standardized financials from SEC EDGAR XBRL filings, filing links,
Treasury yields from FRED, and market prices and beta. Every number comes back
with its source: the XBRL concept, the filing accession and a URL to the filing.

## Why

Anthropic's [financial-services plugins](https://github.com/anthropics/financial-services)
ship `/comps`, `/dcf` and earnings workflows whose skills tell Claude to pull
data from MCP connectors first and to cite every hard-coded input. All of the
bundled connectors are paid terminals (FactSet, S&P Capital IQ, PitchBook,
Morningstar, …). Without a subscription, the skills fall back to web search,
which they explicitly warn against.

This server fills that gap with public sources, and it is built around the
skills' citation requirement instead of treating sources as an afterthought.

## Tools

| Tool | Returns |
|---|---|
| `lookup_company` | Ticker, name, CIK and exchange for a ticker or name search |
| `get_financials` | Annual + LTM income statement, cash flow and balance sheet; derived EBITDA, FCF, total debt, net debt; per-value citations |
| `get_filings` | Recent 10-K / 10-Q / 8-K (etc.) with document and index URLs |
| `get_earnings_release` | Text of the latest (or an earlier) earnings press release from its Item 2.02 8-K, tables kept as rows, paged |
| `get_market_data` | Price, cover-page shares outstanding, market cap, 5-year monthly beta vs the S&P 500 |
| `get_treasury_yield` | Latest constant-maturity Treasury yield (3M–30Y) from FRED |
| `get_comps` | Peer table: market cap, EV, LTM revenue/EBITDA/net income, EV/Revenue, EV/EBITDA, P/E, with median and mean |

All tools are read-only. Nothing needs an API key.

### Example: `get_comps(["KO", "PEP", "KDP", "MNST"])`, run 2026-09-29

| Ticker | Period | Mkt cap ($B) | EV ($B) | EV/Rev | EV/EBITDA | P/E | Beta |
|---|---|---:|---:|---:|---:|---:|---:|
| KO | LTM to 2026-04-03 | 374 | 407 | 8.26 | 26.23 | 27.27 | 0.34 |
| PEP | LTM to 2026-06-13 | 176 | 226 | 2.33 | 12.57 | 16.81 | 0.35 |
| KDP | LTM to 2026-06-30 | 42 | 71 | 3.52 | 18.51 | 29.59 | 0.40 |
| MNST | LTM to 2026-06-30 | 41 | — | — | — | 19.22 | 0.52 |

The notes that came back with those rows are the point of the design:

- **KO**: EDGAR lists a 10-Q filed 2026-07-29 that the XBRL API does not
  include yet, so the figures stop at Q1. The tool says so instead of passing
  stale LTM off as current.
- **KDP**: non-operating items of −1.3B exceed 25% of operating income, so the
  P/E is distorted and EV/EBITDA should carry more weight.
- **MNST**: no debt concepts are reported, so EV is left null rather than
  assuming zero debt. A separately labeled `enterprise_value_if_debt_free`
  (37B) is offered, to use once the balance sheet confirms it.

## Does it help? (evals)

Eight `claude plugin eval` cases, each run with and without the plugin (both
arms have web search), on live data:

| | With plugin | Without |
|---|---:|---:|
| Mean score (8 cases, 3 runs each) | **0.96** | 0.73 |
| Bank valuation: rejects EV/EBITDA, uses P/E or P/B | 1.00 | 0.33 |
| Peer comps: SEC-cited, data problems flagged | 1.00 | 0.33 |

The gains come from judgment, not lookup: on single historical facts a web
search can find, the baseline does as well. The suite was audited against
transcripts before the numbers were trusted, which turned up three grader
bugs and one product gap. Details, per-case results and caveats are in
[plugin/evals/RESULTS.md](plugin/evals/RESULTS.md).

## Install

Requires [uv](https://docs.astral.sh/uv/). SEC requires automated clients to
send a User-Agent with a contact, so you provide your name and email once.

**As a Claude Code plugin** (adds the server plus a skill on citing the data):

```bash
claude plugin marketplace add nathanaelhub/open-finance-mcp
claude plugin install open-finance@open-finance
claude plugin configure open-finance   # set sec_user_agent: "Your Name you@example.com"
```

If the contact is missing, the server still starts and its tools answer with
an error saying how to set it, rather than silently not loading. It can also
come from the `OPEN_FINANCE_SEC_USER_AGENT` environment variable.

It works alongside `financial-analysis@claude-for-financial-services`: the
`/comps` and `/dcf` skills find an MCP data source and use it.

**As a plain MCP server** (Claude Code, Claude Desktop or any MCP client):

```bash
claude mcp add open-finance \
  -e SEC_USER_AGENT="Your Name you@example.com" \
  -- uvx --from git+https://github.com/nathanaelhub/open-finance-mcp open-finance-mcp
```

Responses are cached on disk (`~/.cache/open-finance-mcp`, or
`$OPEN_FINANCE_MCP_CACHE`): company facts for a day, prices for 15 minutes.
SEC requests are spaced to stay under the 10 requests/second fair-access limit.

## How the numbers are built

XBRL data is messier than it looks. Each rule below exists because a real
filer broke the simple version:

- **Concepts resolve per period, not per company.** Tags change over time:
  Caterpillar's `NetIncomeLoss` stops in 2010 and continues as
  `NetIncomeLossAvailableToCommonStockholdersBasic`. Each metric has a priority
  list, the first concept with a value *for that period* wins, and the
  concept used is returned with the value.
- **Restatements win; labels come from the original 10-K.** A 10-K repeats
  prior years as comparatives and may restate them. Values come from the most
  recent filing, and each value cites it. The fiscal-year label comes from the
  period's original 10-K, because a year-end date misleads for retailers (Home
  Depot's fiscal 2025 ends 1 Feb 2026).
- **LTM = FY + YTD − prior-year YTD, from one concept.** JPMorgan tags annual
  revenue as `Revenues` and quarterly as `RevenuesNetOfInterestExpense`, so an
  LTM mixing concepts could combine different definitions. If no single
  concept covers all three periods, LTM is null. Labels give the exact end
  date, not "6M", because 52/53-week filers have 12- and 16-week quarters.
- **Total debt never double counts.** `DebtCurrent` already includes commercial
  paper and the current portion of long-term debt; `LongTermDebt` already
  includes its current portion. The formula used is returned (e.g.
  `ltd_noncurrent + ltd_current + commercial_paper`), and matches Apple's
  FY2024 10-K to the dollar ($106.629B). Operating leases are excluded.
- **Missing is null, never zero.** Caterpillar's 10-Qs tag debt only by
  segment, which the XBRL API omits, so LTM debt is null with a reason.
- **Share counts handle multiple classes.** The cover-page count is summed
  across classes. Alphabet reports its cover page only per class, which the API
  drops, so the server falls back to the balance-sheet total and says the
  price is for one class.
- **Beta uses completed months.** Yahoo's monthly series ends with the
  in-progress month; that partial "return" is dropped. Beta is OLS on the last
  60 completed monthly returns against `^GSPC` (a price index, no dividends).
- **Errors the model can act on.** The MCP SDK hides unexpected exceptions
  behind "Error executing tool", so every anticipated failure is a readable
  tool error: an unknown ticker points to `lookup_company`, and a new registrant
  with no history (ExxonMobil's new holding company, CIK 2115436) is explained
  rather than returned as empty tables.

## Earnings releases: the newest quarter

SEC's XBRL API can trail EDGAR by weeks (Coca-Cola's July 10-Q, above). The
press release is furnished on results day as an exhibit to an 8-K tagged
Item 2.02, so `get_earnings_release` finds the latest such 8-K, picks the
EX-99 exhibit from the filing's index page (file names vary:
`a2026q2earningsreleaseex-9.htm`, `q2fy27pr.htm`, …) and converts it to text.
Financial tables come through as rows, with the `$`, `(` and `%` cells that
filings use for alignment joined back to their numbers:

```
EMEA | $3,240 | $3,176 | 2 | $1,309 | $1,325 | (1)
Consolidated | $13,380 | $12,535 | 7 | $4,672 | $4,280 | 9
```

Tested across Apple, Microsoft, NVIDIA, Alphabet, JPMorgan, Caterpillar,
PepsiCo, Coca-Cola, Walmart and Tesla. Item 2.02 also covers non-earnings
results announcements (Tesla files delivery numbers under it), so the tool
tells the model to confirm what the document is rather than guessing.

## Limitations

- US-GAAP SEC filers only. IFRS filers (20-F/40-F) are not supported.
- The XBRL company-facts API excludes dimensional (segment/class) facts and
  can lag EDGAR by weeks. Both cases are flagged rather than hidden.
- Prices come from Yahoo Finance's unofficial chart endpoint. They are labeled
  as unofficial so a model citing them says so; verify before publishing.
- EBITDA is operating income + D&A as reported, not adjusted EBITDA.

## Development

```bash
uv sync
uv run pytest            # 57 tests, offline: real filings trimmed into tests/fixtures
SEC_USER_AGENT="Name you@example.com" uv run python scripts/make_fixtures.py   # refresh fixtures
```

Tests run the tools through an in-process MCP client with HTTP mocked, and
once over stdio as a subprocess, which is how Claude Code launches the server.
CI covers Python 3.11–3.14.

Data: [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[FRED](https://fred.stlouisfed.org/). Not investment advice; outputs are
drafts for review by a qualified person.

MIT licensed.
