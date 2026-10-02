---
description: "Home Depot's fiscal 2025 ends 1 Feb 2026; labeling by calendar year is the classic mistake."
tags: [accuracy]
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

What was Home Depot's (HD) revenue for fiscal 2025, and on what date did that fiscal year end? Cite the filing.
