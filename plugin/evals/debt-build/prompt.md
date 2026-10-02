---
description: "Apple FY2024 total debt of $106.629B from three components, without double counting."
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

What was Apple's total debt at the end of fiscal 2024? Break it into its components and cite the filing.
