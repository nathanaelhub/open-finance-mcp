---
description: "EV/EBITDA is asked for a bank; the right answer is that it is not meaningful."
tags: [financials]
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

What is JPMorgan Chase's (JPM) EV/EBITDA, and how does its valuation compare on the multiple you'd actually use for it? Cite the SEC filings behind your figures.
