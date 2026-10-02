---
description: "Peer comps with three data traps: a lagging XBRL feed (KO), non-operating items (KDP), and a company with no reported debt (MNST)."
tags: [comps, warnings]
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

Build a quick trading-comps table for Coca-Cola (KO), PepsiCo (PEP), Keurig Dr Pepper (KDP) and Monster Beverage (MNST): market cap, enterprise value, EV/EBITDA and P/E, plus the peer median. Cite the SEC filing behind each company's figures and flag anything that makes a number unreliable.
