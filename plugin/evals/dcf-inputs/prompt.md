---
description: "Five DCF inputs, each needing a value, date and source."
tags: [dcf]
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
  - WebSearch
  - WebFetch
  - Skill
---

I'm building a DCF for Apple (AAPL). Gather the inputs: the current risk-free rate, Apple's beta, net debt, diluted shares outstanding and latest-fiscal-year free cash flow. Give the value, date and source for each input.
