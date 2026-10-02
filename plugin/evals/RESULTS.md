# Eval results

Run 2026-10-02 with `claude plugin eval` (Claude Code 2.1.287), model
`claude-sonnet-5`, Haiku judges (3 votes per LLM grader), 3 runs per arm,
real MCP server against live SEC/FRED/Yahoo data. **With** = this plugin
loaded; **without** = the same prompt with no plugin. Both arms have
WebSearch and WebFetch, which is what Claude falls back to without a data
connector. Score = weighted share of graders passed, averaged over runs.

| Case | With | Without | Δ |
|---|---:|---:|---:|
| `bank-multiples` | 1.00 | 0.33 | +0.67 |
| `consumer-comps` | 1.00 | 0.33 | +0.67 |
| `dcf-inputs` | 1.00 | 0.92 | +0.08 |
| `debt-build` | 1.00 | 1.00 | +0.00 |
| `distorted-pe` | 1.00 | 0.78 | +0.22 |
| `ifrs-filer` | 1.00 | 1.00 | +0.00 |
| `new-registrant` | 0.78 | 0.44 | +0.33 |
| `retailer-fiscal-year` | 0.89 | 1.00 | −0.11 |
| **Mean** | **0.96** | **0.73** | **+0.23** |

Total cost of the run: about $10 (48 + 6 agent runs, plus judges).

## Reading it

- **The gains come from judgment, not lookup.** On single historical facts a
  web search can find (Apple's FY2024 debt, Home Depot's fiscal year, Toyota
  being an IFRS filer), the baseline does as well. Without the plugin, the
  bank answer never gave a bank-appropriate multiple with a number (0 of 3
  runs) and presented an EV/EBITDA for JPMorgan in 1 of 3; the beverage comps
  never flagged a data problem specific to these companies (0 of 3) and gave
  Monster an EV with no word on its debt in 1 of 3. With the plugin, those
  graders passed in every run, because the warnings come back with the data.
- **Citations.** Without the plugin, none of the 6 comps and bank answers
  cited an SEC filing; with it, all 6 did.
- **Where it lost.** One `retailer-fiscal-year` run with the plugin failed the
  year-end-date regex (that transcript was not kept; two re-runs with
  transcripts both passed, so it may be a phrasing the regex misses). `new-registrant` is noisy in
  both arms (see below).

## How the suite was audited

The first full run's failures were checked against transcripts before any
number was trusted. That found grader problems, not answer problems, which
were fixed before the run above:

- The Exxon grader failed accurate, well-cited answers in **both** arms because
  it required explaining the holding-company change. It now checks FY2022
  revenue against the filing ($413.68B total revenues or $398.68B sales) and
  judges only whether sources are checkable.
- Prompts graded on SEC citations now ask for them, so the baseline is not
  penalized for an unstated requirement.
- Two regexes missed valid phrasings ("10-Year U.S. Treasury",
  "February 1st, 2026").

The transcripts also found a product gap: once XOM moved to the new holding
company, the predecessor's history (CIK 34088) was unreachable by ticker. The
tools now accept a CIK, and the error message points to it. `new-registrant`
above is a separate 3-run re-run after a final judge-criteria clarification:
a figure cited to a later 10-K as a comparative year counts as sourced. One
correct, fully cited plugin-arm answer still drew a FAIL from the Haiku judge,
so treat that row as noisy.

## Caveats

3 runs per arm is a small sample, the data is live (the Coca-Cola lag will
disappear once SEC's API catches up), and the LLM graders are Haiku. The
numbers show where the plugin changes behavior; they are not a benchmark.

## Re-running

```bash
SEC_USER_AGENT="Name you@example.com" uv run python scripts/run_evals.py --runs 3
```

`scripts/run_evals.py` points a temp copy of the plugin at this checkout's
server, because eval runs don't pass plugin userConfig or the shell
environment to a plugin's MCP server.
