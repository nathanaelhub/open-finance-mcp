# Eval results

Run 2026-10-02 with `claude plugin eval` (Claude Code 2.1.287), model
`claude-sonnet-5`, Haiku judges (3 votes per LLM grader), 3 runs per arm,
real MCP server against live SEC/FRED/Yahoo data, transcripts kept.
**With** = this plugin loaded; **without** = the same prompt with no plugin.
Both arms are granted WebSearch and WebFetch. "Web" counts the baseline runs
that actually used them (checked in each transcript).

| Case | With | Without | Δ | Web | $/run with | $/run without |
|---|---:|---:|---:|---:|---:|---:|
| `ko-latest-quarter` | 1.00 | 0.07 | +0.93 | 0/3 | $0.13 | $0.04 |
| `ifrs-filer` | 1.00 | 0.33 | +0.67 † | 3/3 | $0.16 | $0.50 |
| `new-registrant` | 0.78 | 0.44 | +0.33 † | 3/3 | $0.11 | $0.20 |
| `distorted-pe` | 1.00 | 0.78 | +0.22 | 3/3 | $0.08 | $0.18 |
| `consumer-comps` | 1.00 | 0.83 | +0.17 | 3/3 | $0.18 | $2.96 |
| `nvda-earnings-note` | 1.00 | 0.93 | +0.07 | 3/3 | $0.13 | $0.19 |
| `bank-multiples` | 1.00 | 1.00 | 0.00 | 3/3 | $0.22 | $0.41 |
| `dcf-inputs` | 1.00 | 1.00 | 0.00 | 3/3 | $0.12 | $0.48 |
| `debt-build` | 1.00 | 1.00 | 0.00 | 3/3 | $0.10 | $0.17 |
| `retailer-fiscal-year` | 1.00 | 1.00 | 0.00 | 3/3 | $0.09 | $0.11 |
| **Mean** | **0.98** | **0.74** | **+0.24** | 27/30 | **$0.13** | **$0.52** |

† Judge noise, not plugin advantage: see below.

Total cost of the run: about $20, most of it the baseline's web research.

## What the evidence supports

- **Fresh quarters.** Asked for Coca-Cola's Q2 2026 numbers, the baseline
  never searched: it assumed the quarter was past its knowledge and declined
  (0.07). With the plugin, every run read the earnings release, which is filed
  weeks before the quarter reaches SEC's XBRL API, and answered with GAAP and
  non-GAAP EPS correctly labeled (1.00).
- **Cost.** With the plugin, a run costs $0.13 on average against $0.52
  without; on peer comps it is $0.18 against $2.96, because the baseline
  searches and fetches page after page to assemble the same table.
- **Consistency.** With the plugin, no case averaged below 0.78. Without it,
  scores within a case ranged from 0 to 1 on four of ten cases.
- **Judgment, when the baseline searches: mostly a tie.** A web-searching
  baseline matched the plugin on bank multiples, DCF inputs and the single
  historical facts, and came close on comps and the NVIDIA note. The remaining
  gaps (`distorted-pe`, `consumer-comps`) are one or two runs that missed a
  caveat.

## † Rows not to read as plugin wins

- `ifrs-filer`: a failed baseline answer, read in full, identified Toyota as an
  IFRS 20-F filer, gave yen figures with the March fiscal year, flagged its
  derived EBITDA and linked the actual 20-F filings. Its real flaw (using
  FY2023–FY2025 when the FY2026 20-F was already out) isn't in the rubric, so
  the judge's FAIL doesn't follow its own criteria.
- `new-registrant`: noisy in both arms across every run so far; the Haiku
  judge has failed correct, fully cited answers on both sides.

## Correction

An earlier version of this page reported, from a run without kept
transcripts, a baseline of 0.33 on bank multiples and on comps, and
attributed the gap to judgment. In this run, with transcripts, the baseline
used web search in 27 of 30 runs and scored 1.00 and 0.83 on those cases.
The earlier gaps most likely came from baseline runs that never searched;
without transcripts that can't be confirmed, so those numbers have been
withdrawn rather than averaged in.

## How the suite was audited

Failures were checked against transcripts before any number was used:

- The first run found three grader bugs: the Exxon grader failed accurate,
  well-cited answers in both arms; prompts graded on SEC citations didn't ask
  for them; two regexes missed valid phrasings ("10-Year U.S. Treasury",
  "February 1st, 2026").
- Transcripts also found two product gaps, both fixed: the server didn't start
  when the SEC contact was unset (v0.1.1), and a predecessor company was
  unreachable by ticker (tools now accept a CIK).
- This run found the baseline-search issue above and the two noisy rows.

## Caveats

3 runs per arm is a small sample. The data is live: the Coca-Cola case
depends on SEC's API lagging, which ends when the API catches up (the case
is pinned to Q2 2026, so the expected answer won't change). The LLM graders
are Haiku. Read this as where the plugin changes behavior and cost, not as a
benchmark.

## Re-running

```bash
SEC_USER_AGENT="Name you@example.com" uv run python scripts/run_evals.py --runs 3 --keep-temp
```

`scripts/run_evals.py` points a temp copy of the plugin at this checkout's
server, because eval runs don't pass plugin userConfig or the shell
environment to a plugin's MCP server. Keep transcripts (`--keep-temp`):
scores without them can't be audited.
