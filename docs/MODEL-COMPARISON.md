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

## Results

Sonnet 5.5, default settings, code frozen at `00af077` (verified unchanged before the runs). No
stop fired, nothing was published. The Opus page is untouched.

| | Doc 1: Council 2026-10-22 | Doc 2: Council 2026-10-08 | Doc 3: FGPS committee 2026-09-08 |
|---|---|---|---|
| Facts extracted | 60 | 48 | 10 |
| **Facts passing every check** (needs 80%) | 55 (92%) **pass** | 46 (96%) **pass** | 7 (70%) **FAIL** |
| **Voted-item coverage** (needs 66%) | 26 of 29 (90%) **pass** | 9 of 9 (100%) **pass** | n/a (0 recorded pass/fail) |
| **Accepted facts the city's record contradicts** (needs 0) | 0 **pass** | 0 **pass** | 0 **pass** |
| **"May need Opus" stop** (needs none) | none **pass** | none **pass** | none **pass** |
| Fact-checker flags (not scored) | 0 of 60 | 0 of 48 | 0 of 10 |
| Accepted vote facts / confirmed by the city's record | 42 / 42 | 32 / 32 | 2 / 0 (their outcome is "other", which can't be checked against the record) |
| Summary sentences published / written | 6 / 8 | 7 / 9 | 6 / 9 |
| Tokens in / out | 70.2k / 15.2k | 56.3k / 13.5k | 25.5k / 4.7k |
| Turns | 6 | 6 | 6 |
| Wall time | 90 s | 85 s | 40 s |
| Extractor stage (in / out, time) | 24.9k / 10.9k, 61 s | 19.8k / 8.5k, 49 s | 9.3k / 2.1k, 15 s |
| Summarizer stage | 9.3k / 1.0k, 8 s | 8.2k / 1.6k, 12 s | 5.1k / 0.9k, 9 s |
| Fact-checker stage | 36.0k / 3.3k, 21 s | 28.2k / 3.5k, 24 s | 11.1k / 1.7k, 16 s |
| **Document passes?** | yes (after the earlier fixes) | **yes** | **NO** |

The two new documents together used 81.8k tokens in and 18.3k out over 125 seconds, under the
~150k tokens estimated for both.

**Overall: the pre-registered test FAILED.** Document 2 met every criterion with room to spare.
Document 3 missed the 80% bar: 7 of 10 facts passed.

## Why those facts were rejected: all ten, read and classified

Document 3 has 10 facts, so 70% against 80% is a one-fact difference. The point is what the three
rejections are.

| Document | Fact | Check that rejected it | Classification |
|---|---|---|---|
| 2 | "Resolution 260897 passed with all 13 members voting aye" | `13` isn't in the quote | **Correct by design.** The statement says more than its quote: the 13 is the model's own count of the names listed. It is true (the city's roll call has 13 Ayes). |
| 2 | Same for Ordinance 260893 | same | **Correct by design**, same reason. |
| 3 | "Advanced...for the ordinance creating Section 2-90" | `2` and `90` aren't in the quote | **Correct by design.** The quote is the "Adv and Do Pass" line; the section number sits elsewhere. The item is left uncovered, not misreported. |
| 3 | "Riverfront CID ordinance was held in committee until September 22" | `api_disagrees` | **Over-strict: a bug in my check.** The city's record calls the action "Hold on Agenda"; my vocabulary looks for the word "held" and doesn't find it in "Hold". The claim is true, and the fact-checker said so. |
| 3 | "Mississippi Lime ordinance was held until September 22 and transferred" | `api_disagrees` | **Over-strict**, same bug. |

For document 1 (earlier): lot number (`Lot 1`) and street address (`1815 Paseo`) in the statement but
not the quote are correct by design; a quote too short to prove anything ("Willett voted Nay") is
correct by design; the two about Resolution 260885 are an **over-strict limitation**: the minutes
print a committee-substitute's wording, which differs from the original title in the API, so the
check couldn't place the item and then demanded its number in the quote. So that is why 55 of 60
passed rather than 60: three kinds of reason, of which "the statement says more than its quote"
is the check doing its job, and "the check couldn't place the item" and "the check's word list
missed the city's wording" are mine to fix.

If the over-strict items were fixed, document 3 would be 9 of 10. **I'm not counting that as a pass.**
The criteria said failure is failure, the code was frozen, and the fix is a ticket (T-11). It
is a statement about my checker, not about Sonnet: all 10 facts in document 3 are true as far as I
can tell.

## What I make of zero fact-checker flags

Across the three Sonnet coverage-prompt runs the checker flagged 0 of 118 claims. Three readings:

1. **The facts really were right.** For votes there is independent evidence: all 74 accepted vote
   facts in documents 1 and 2 match the city's own record, and the 13-aye claims are true. The
   extractor prompt also now tells the extractor not to write "authorizes" for an item that was only
   introduced, which is exactly the mistake the checker caught on the first prompt and on Opus. So
   there was less for it to catch.
2. **The checker is lenient.** It marked "SUPPORTED" claims that my code correctly rejected (the
   13-member count, Section 2-90). It is told what the code found but is not asked to second-guess
   it, so its agreement with code only shows on the cases above.
3. **It reads carefully.** Its reasons are specific ("13 names listed as Aye and no Nay", dates,
   section numbers), which is not what a rubber stamp looks like.

I can't separate 1 from 2 from this data. **T-5 (planted errors) should come before relying on the
checker or adding more documents:** it is the only way to measure what the checker catches. Until
then, the real defence is the code layer and the city's vote record, not the checker.

## Recommendation

- **Report the test as failed**, as pre-registered: documents 1 and 2 pass, document 3 does not.
- **Keep Sonnet 5.5 as the default.** The failure is in my verifier (a vocabulary bug and a strict
  rule), not in Sonnet, and nothing in this test shows Sonnet doing worse than Opus: on the two
  Council documents it covered 90% and 100% of voted items with 0 contradictions. But it is not
  proven beyond Kansas City Council minutes, and committee minutes are untested in the sense that
  matters.
- **Order of work:** T-5 first (is the checker real?), then T-11 (city wording for held/referred/etc.)
  and re-score the saved outputs for free as a labelled post-hoc re-score, then T-12 and T-13.
  Only then consider scaling to more documents.

---

# Test 3: does the fact-checker catch planted errors? (T-5)

Test 2 left one question open: the Sonnet fact-checker had flagged 0 of 118 real claims, which is
what a good checker facing good facts would do and also what a rubber stamp would do. T-5 builds fake
claims and slips them into the checker's input to tell the two apart.

**How the fakes are made** (`pipeline/canary.py`). Each is a copy of a claim that already passed the
code checks, made false in a way code can't see (the quote, numbers and matter number stay right):
`flip_outcome` ("adopted" becomes "rejected", "held" becomes "approved", "recommended do pass"
becomes "recommended against passage"), `overstate` ("passed" becomes "passed unanimously" for a
vote the city's roll call shows had Nay votes), `swap_name` (the councilmember who voted no is
replaced by one who voted aye), and `swap_body` (the vote is attributed to a different committee or
body). The fakes get ordinary ids continuing the real sequence, and nothing in the input marks them.
They are never published: their verdicts are split off before `decide()`, and tests prove it.

**Run:** the fact-checker only, on the saved real runs of three documents (the Oct 22 and Oct 8
Council minutes and the Sept 8 committee minutes), each with its real claims plus the fakes, Sonnet
5.5. `python -m pipeline.run canary-eval <doc>`.

| | Oct 22 Council | Oct 8 Council | Sept 8 committee | Total |
|---|---|---|---|---|
| Fakes planted | 4 | 4 | 2 | **10** |
| **Caught by the fact-checker** | 4 | 4 | 2 | **10 of 10** |
| Code alone would also have caught | 2 | 2 | 0 | 4 |
| Real claims the checker flagged in the same call | 0 of 60 | 0 of 48 | 0 of 10 | **0 of 118** |
| Tokens in / out | 37.3k / 4.2k | 29.5k / 3.5k | 12.1k / 1.9k | 78.9k / 9.6k |
| Turns / wall time | 2 / 27 s | 2 / 22 s | 2 / 14 s | 6 / 63 s |

By kind: outcome flips 5 of 5 (code caught 4 of those: the committee's wording isn't checkable until
T-11), wrong body 3 of 3, swapped councilmember 1 of 1, false "unanimously" 1 of 1. Only the checker
could catch the last three kinds (5 fakes): it did, all of them.

**It caught them for the right reasons.** Each reason names the specific wrong thing: "'rejected' is
wrong; the source says the motion carried"; "Nay votes were Willett and Rogers, not Lucas; Lucas voted
Aye"; "'unanimously' is wrong; Willett and Duncan voted Nay"; "It was a full Council meeting, and the
item sat under the Neighborhood committee heading, not an FGPS committee meeting". Real claims in
the same calls were not flagged, so it is not saying "no" to everything.

**What this settles, and what it doesn't.** The checker is not a rubber stamp: on this kind of error it
said no every time and did not raise false alarms. So the 0 flags on real claims is evidence the
facts were right, not evidence the checker is blind. It does not settle:
- **Sample size:** 10 fakes from 3 documents. A catch rate of 10 of 10 is compatible with a true
  rate well under 100%.
- **Difficulty:** these fakes are explicit contradictions of text the checker can see. Subtler errors
  (a wrong date, a dropped qualifier like "as substituted", a wrong organisation, an off-by-one count)
  are untested. See T-14.
- **One model:** the checker was Sonnet 5.5. Only Kansas City minutes, one fake template set.
- **Cost of the safeguard:** nightly runs now carry 4 fakes in the fact-checker call, about 4 extra
  claims on 60, which is a few percent of that stage's tokens.

**Effect on the open decision:** the main reason to hold back the nightly schedule and the public site
(an untested checker) is weaker, not gone. See the recommendation to the user in the session report.
