---
description: "Coca-Cola's Q2 2026 is in its earnings release and 10-Q, but not yet in the XBRL API behind get_financials. Truth: net revenues $13,380M, GAAP diluted EPS $1.03 (comparable non-GAAP $0.97)."
tags: [earnings, freshness]
plugins: ["../.."]
runs: 2
max_turns: 15
timeout_seconds: 420
model: claude-sonnet-5
allowed_tools:
  - mcp__plugin_open-finance_open-finance__lookup_company
  - mcp__plugin_open-finance_open-finance__get_financials
  - mcp__plugin_open-finance_open-finance__get_filings
  - mcp__plugin_open-finance_open-finance__get_market_data
  - mcp__plugin_open-finance_open-finance__get_treasury_yield
  - mcp__plugin_open-finance_open-finance__get_comps
  - mcp__plugin_open-finance_open-finance__get_earnings_release
  - WebSearch
  - WebFetch
  - Skill
---

What were Coca-Cola's (KO) net revenues and diluted EPS for the second quarter of 2026? Cite the source document.
