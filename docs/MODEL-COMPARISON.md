# Model comparison: Opus 5.5 vs Sonnet 5.5, same document

Three real runs on one document, 2026-10-29: Kansas City Council minutes of 2026-10-22
(`kc-19561-minutes`, 28 pages, 29 agenda items with a recorded pass/fail), all on the Claude Max
subscription, all reading the same saved copy of the document:

1. **Opus 5.5**, original extractor prompt (run before the Sonnet default).
2. **Sonnet 5.5, first prompt:** the same prompt ("precision matters far more than coverage").
3. **Sonnet 5.5, coverage prompt:** extractor rewritten to ask for one fact per voted item and per
   money item, with the exactness rules unchanged (T-9).

Saved agent outputs: `tests/fixtures/kansascity/runs/{opus,sonnet-prompt1,sonnet-prompt2}/`. Full
run folders for the Sonnet runs are in `experiments/` (gitignored). This is one document and one
run each: a first look, not a benchmark.

## Side by side (all three scored by the same, current `verify.py`)

| | Opus 5.5 | Sonnet, first prompt | Sonnet, coverage prompt |
|---|---|---|---|
| Facts extracted | 37 | 7 | **60** |
| Facts passing every check | 32 (86%) | 5 (71%) | **55 (92%)** |
| **Voted items covered** (of 29) | 19 (66%) | 4 (14%) | **26 (90%)** |
| Accepted vote facts | 23 | 0 | 42 |
| Accepted facts the city's vote record confirms | 23 | 1 | 42 |
| Accepted facts the city's record contradicts | 0 | 0 | 0 |
| Fact-checker verdicts S / P / U | 36 / 1 / 0 | 6 / 1 / 0 | 60 / 0 / 0 |
| Code and checker agree | 32 of 37 | 5 of 7 | 55 of 60 |
| Summary sentences published / written | 6 / 8 | 5 / 7 | 6 / 8 |
| "This may need Opus" stop | n/a | not triggered | not triggered |
| **Tokens in / out** | 62.5k / 13.7k | 55.1k / 5.7k | 70.2k / 15.2k |
| **Turns** | 6 | 6 | 6 |
| **Wall time** | 116 s | 47 s | 90 s |
| API-equivalent units (comparison only) | 0.77 | 0.28 | 0.42 |

Per stage (tokens in / out, seconds):

| Stage | Opus 5.5 | Sonnet, first prompt | Sonnet, coverage prompt |
|---|---|---|---|
| extractor | 23.8k / 7.7k, 60 s | 24.3k / 3.3k, 25 s | 24.9k / 10.9k, 61 s |
| summarizer | 6.7k / 2.0k, 21 s | 4.5k / 0.8k, 8 s | 9.3k / 1.0k, 8 s |
| fact-checker | 32.0k / 4.0k, 35 s | 26.3k / 1.6k, 14 s | 36.0k / 3.3k, 21 s |

Between Opus and the Sonnet coverage run, 20 items have an accepted vote fact in both, and the
recorded outcome agrees on all 20. Of the 29 voted items, Sonnet covers 8 that Opus doesn't
(260910, 260912, 260916, 260919, 260932, 260933, 260945, 260946) and Opus covers 1 that Sonnet
doesn't (260885). Neither covers 260907 and 260947: in each case the fact was rejected because a
number in the statement (a lot number, a street address) isn't in the quote.

## What happened, in order

1. **First prompt: 7 facts.** Sonnet's extractor read "precision matters far more than coverage" as
   "write few facts". Both models spent about 2k thinking tokens; Sonnet wrote 3.3k tokens of output
   against Opus's 7.7k. It covered 4 of 29 voted items. The facts it did write were accurate.
2. **Coverage prompt, as first scored: coverage 16 of 29 (55%), pass rate 38%.** That missed the bar
   I'd set before the run (at least 17 of 29, within 10 points of Opus's 66%, and a pass rate of
   80% or better). But all 37 rejections came from my own code checks (34 of them from the "quote
   belongs to another item" rule) and the fact-checker had marked every one of those claims
   SUPPORTED.
3. **Reading those disagreements showed my check was wrong, not Sonnet.** Sonnet's vote quotes are
   boilerplate ("A motion was made that this Ordinance be Passed...") that repeats under every
   passed item. My matter-block check looked only at the *first* place the quote occurs in the
   document, so it blamed the wrong item. The correct rule is whether the quote occurs inside the
   claimed item's own block; a boilerplate quote still can't back a claim about an item whose block
   lacks it. Two smaller defects came out of the same pass: "63rd Street" in a statement was counted
   as the number 63, and my first fix for that cut "63rd" down to "6" (caught by checking, fixed,
   and tested). Opus's saved output scores identically under the old and new code. Sonnet's
   first-prompt output does too.
4. **All three runs were re-scored with the same fixed code**, with no model call, giving the table
   above. The pre-fix figure for the coverage run is in the previous point so you can see what the
   fix changed. I also found and closed a hole while doing it: a summary headline could restate a
   rejected fact (it was only checked against "some sentence was published"). It now requires every
   claim it was checked against to have been accepted, which makes headlines fall back to a plain
   title more often until T-10 gives the headline its own claim list.

## Did the coverage prompt close the gap?

**Yes, on this document, by the metric and the precision evidence, with one thing you should weigh.**

- **Coverage:** 26 of 29 voted items against Opus's 19 of 29, and 90% against 66%. Well past the
  17-of-29 bar.
- **Accuracy:** 55 of 60 facts pass every check (92%). All 42 accepted vote facts match the city's
  own vote record, which is independent of both agents and my checks; none contradicts it. The 5
  rejected facts are an item the minutes layout made impossible to locate, so its number isn't
  proven (2: both about 260885), a lot number or street address in the statement that the quote
  lacks (2), and a quote too short to prove anything (1).
- **The thing to weigh:** the pre-fix scoring did *not* meet the bar, and I changed the check before
  concluding. The change is principled and applied identically to all three runs, tests pin the
  boilerplate-quote case both ways, and the independent vote-record agreement is the strongest
  evidence. But it is still my reading of my own check. If you'd rather treat the pre-fix result as
  "gap not closed", the next step is the per-stage setting (extractor on Opus, the other two on
  Sonnet), which I have not built.
- **What this does not show:** the Sonnet fact-checker flagged none of 60 claims, so it tells us
  nothing about how well it catches errors; Opus's checker caught one real error in 37 and Sonnet's
  caught one in 7 on the first prompt. The canary test in T-5 is what measures that. The 40%
  coverage floor in `verify.py` is a first guess from this one document.

## Verdict

**Sonnet 5.5 is good enough as the default for all three stages, with the coverage prompt.**
Reasons: it matches Opus on accuracy and beats it on coverage here (26 vs 19 of 29), uses about
the same tokens (70k in / 15k out against 62k / 14k) in about three quarters of the time, and the
cost of being wrong is bounded by the checks and by the new "too few facts" stop. Opus stays
available as an explicit, user-chosen override (`--model`). No per-stage model setting was added.
Run it on a second and a third document, and add the T-5 canaries, before trusting this beyond
Kansas City Council minutes.

Nothing here has been published or pushed. The published page is still the Opus run.

---

# Test 2: two more documents (pre-registered)

Written and committed **before any run**, so the bar can't move afterwards. Document 1 above was
scored after I had changed my own check; this test exists to see whether the default setup holds
when nothing is changed in the middle.

## Frozen

Code is frozen at commit `00af077`. For the duration of this test nothing changes in
`pipeline/verify.py` (every check and every threshold: `FUZZY_MIN` 0.92, `MIN_QUOTE_CHARS` 20,
`COVERAGE_MIN` 0.40, `COVERAGE_MIN_ITEMS` 5, `MISSING_VERDICT_LIMIT` 0.10), the three agent
prompts, or the schemas. If a check looks over-strict while I read the results, it becomes a ticket
in TASKS.md. It is not changed and the run is not re-scored.

## Documents, and how they were picked

Both come from the live Legistar API, chosen by a mechanical rule before any model ran:

| | Document | Why |
|---|---|---|
| 2 | `kc-19539-minutes`: Council, 2026-10-08, 68 agenda items, 9 with a recorded pass/fail | The most recent Council minutes other than document 1 (2026-10-22). |
| 3 | `kc-19460-minutes`: Finance, Governance and Public Safety Committee, 2026-09-08, 11 items, 0 with a recorded pass/fail | The most recent committee minutes, picked because a different kind of meeting is a better test than another Council meeting. It is smaller and its results aren't recorded as pass/fail votes. |

Of the 23 minutes documents since July, 14 are Council and 9 are this one committee; no other body
has minutes. Both PDFs returned HTTP 200 when checked on 2026-10-29. If one returns a 404 on the
run, I retry later and run from a saved copy.

## Setup

Sonnet 5.5 only, default settings (agents' `model:` unchanged, no `--model`). No Opus runs: the
city's own vote record is the independent check. Each run goes in its own `experiments/` folder.
Nothing is published and the Opus page isn't touched.

## Pass criteria, per document

A document passes only if it meets every criterion that applies to it:

1. **At least 80% of extracted facts pass every check.**
2. **Voted-item coverage at least 66%** (Opus's level on document 1). Scored only for a document
   where the API records at least 5 pass/fail items (document 2: so at least 6 of 9). Not scored
   for document 3, which has none.
3. **Zero accepted facts that the city's vote record contradicts.**
4. **No "this may need Opus" stop.**

The overall test passes only if both new documents pass. Document 1 is carried over from the
table above (92%, 90%, 0, no stop).

## Reported, not scored

- How many claims the Sonnet fact-checker flagged (PARTIAL or UNSUPPORTED), and what I make of it.
  It flagged none of 60 on document 1.
- Tokens in and out, turns and wall time per stage.
- Every rejected fact, read and classified as a **correct rejection** (the check working as
  designed) or an **over-strict check** (listed as a ticket, not fixed here).

Failures are reported as failures.
