# Model comparison: Opus 5.5 vs Sonnet 5.5, same document

One document, one run each, 2026-10-29: Kansas City Council minutes of 2026-10-22
(`kc-19561-minutes`, 28 pages, 29 agenda items with a recorded pass/fail). Both runs used
the Claude Max subscription, default settings, and the same code (matter-block check
included). The Opus run was made before the Sonnet default; its saved outputs were re-scored
with `redecide`. The Sonnet outputs are in `experiments/sonnet-5-5-run1/` (gitignored); the
Opus outputs are the published page. This is n = 1: treat it as a first look, not a benchmark.

## Side by side

| | Opus 5.5 | Sonnet 5.5 |
|---|---|---|
| Facts extracted | 37 | **7** |
| Facts passing every check | 32 (86%) | 5 (71%) |
| Recorded-vote items covered by an accepted fact | **19 of 29** | **4 of 29** |
| Accepted facts that are votes | 19 | **0** |
| Summary sentences written / published | 8 / 6 | 7 / 5 |
| "This may need Opus" stop | n/a | not triggered |
| Tokens in / out (total) | 62.5k / 13.7k | 55.1k / 5.7k |
| Turns | 6 | 6 |
| Wall time | 116 s | 47 s |
| API-equivalent units (comparison only) | 0.77 | 0.28 |

Per stage (tokens in / out, seconds):

| Stage | Opus 5.5 | Sonnet 5.5 |
|---|---|---|
| extractor | 23.8k / 7.7k, 60 s | 24.3k / 3.3k, 25 s |
| summarizer | 6.7k / 2.0k, 21 s | 4.5k / 0.8k, 8 s |
| fact-checker | 32.0k / 4.0k, 35 s | 26.3k / 1.6k, 14 s |

## What differed

- **Coverage, not accuracy, is where Sonnet fell short.** Sonnet's extractor returned 7
  facts and no vote facts at all, against 37 for Opus. Both spent about 2k thinking tokens on
  the extractor; Sonnet simply wrote far fewer claims. It read "precision matters far more
  than coverage" more strictly than Opus did. Its page would tell a resident about 4 of the
  29 items the Council actually voted on.
- **Its facts held up.** Of Sonnet's 7, 5 passed. The two rejections were the same kind as
  Opus's: "Fund No. 2220" is in the statement but not the quote (code), and an ordinance that
  was only introduced and referred to committee described as "authorizes" (fact-checker).
- **Fact-checker verdicts:** on the 3 claims both runs made (matched by identical quote), the
  verdicts were identical. Sonnet's checker caught the 260948 mistake correctly: the minutes
  show it was only "Move To Introduce... referred to the Finance, Governance and Public Safety
  Committee". That is a meaning error code can't see, the case the agent layer exists for.
  On so few claims this says little about how Sonnet's checker would do on a full set of 37.
- **A blind spot in Sonnet's output:** its spending facts had no `outcome`, so the check against
  the city's own vote record was skipped for them (`api: unchecked`). Only the fact-checker
  stood between those claims and the page. Opus's claims mostly carried an outcome, so the
  API cross-check ran on them.
- **No stop fired**, correctly by the current rules: valid JSON, every claim got a verdict.
  But nothing in the pipeline notices that 7 facts from a 29-vote meeting is thin. See T-8.

## Verdict on Sonnet as the default

**Not good enough as the default for the extractor on the current prompt; probably fine for the
other two stages, but that isn't proven.** Cheaper (about 60% fewer output tokens, 60% less
time) is real, but a page that covers 4 of 29 votes isn't the product. The evidence says the
shortfall is the extractor's coverage under this prompt, not a capability ceiling: the facts
it did extract were as accurate as Opus's. So before moving anything to Opus:

1. Try a coverage-oriented extractor prompt on Sonnet (T-9), judged with the T-8 coverage
   metric. This is the cheapest next step and keeps the Sonnet default.
2. If that doesn't close the gap, ask the user about Opus for the extractor stage only (needs a
   per-stage model setting; today `--model` overrides all three agents).
3. To test the fact-checker fairly, run it on Sonnet over the 37 Opus claims and compare
   verdicts with Opus's. That is about 30k tokens in and 4k out.

Nothing here has been published or pushed.
