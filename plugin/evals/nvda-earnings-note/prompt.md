---
description: "Earnings note from NVIDIA's fiscal Q2 2027 release. Truth: revenue $96.2B (+106% y/y), GAAP EPS $2.46 vs non-GAAP $2.22, Q3 revenue outlook $108.0B +/-2%."
tags: [earnings]
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

Draft a short earnings note on NVIDIA's (NVDA) second quarter of fiscal 2027 for a research team: headline revenue and growth, margins, EPS, and next-quarter guidance. Keep GAAP and non-GAAP figures clearly separated, and cite the source.
