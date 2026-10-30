# Agenda vs minutes: what was planned, what happened, and trends

The idea (the user's words): compare what the agenda planned with what the minutes say happened. What was
forgotten, what got added. Then see whether there are trends over time on certain topics. Agendas stop being
something the pipeline avoids and become a first-class input.

Status: design and a free probe only. Nothing here is in the nightly, and nothing is published until it has been
validated on real meetings and the user has seen it. All numbers in this file come from live Legistar API calls
on 2026-10-29 (no model calls, no plan usage).

## What the probe found

**1. The API already marks planned versus recorded, per row.** Every agenda item row has
`EventItemAgendaSequence` (set when the row is on the agenda) and `EventItemMinutesSequence` (set when the row is in
the minutes), plus the action recorded for the row, who moved it, and the matter's file number and type.

| Meeting | Item rows | On the agenda | In the minutes | Agenda-only rows | Minutes-only rows |
|---|---|---|---|---|---|
| Council 2026-10-22 | 84 | 78 | 84 | 0 | 6 |
| Council 2026-10-08 | 68 | 61 | 68 | 0 | 7 |
| Council 2026-10-01 | 73 | 62 | 72 | 1 | 11 |
| FGPS committee 2026-09-08 | 11 | 11 | 11 | 0 | 0 |

The set of matter numbers on rows with an agenda sequence equals the matter numbers printed in the agenda PDF in
all four meetings (nothing only in one, nothing only in the other). So the structured data and the PDF agree on
what the agenda listed.

**2. A matter has one row per step, and the steps tell the story.** Real examples:

| Matter | Rows (agenda sequence / minutes sequence / action) | What it shows |
|---|---|---|
| 260947 (2026-10-22) | on agenda: Move To Introduce; minutes only: Move to Advance, then Passed | Planned to be introduced; the Council advanced it and **passed it the same day**. |
| 260946 (2026-10-22) | on agenda: Move to Consider; minutes only: Move to Advance, then Passed | Same pattern. |
| 260850 (2026-10-01) | no agenda row at all; minutes only: Move to Reconsider, Move to Advance, Passed | **Added at the meeting**: a reconsideration that was never on the agenda. |
| 260445 (2026-10-22) | on agenda: Held on Docket | **Held, and the matter history shows 9 holds** since its first action on 2026-05-07. |
| 260893 (2026-10-01) | on agenda: Move To Introduce; minutes only: referred | Planned introduction, ended up referred. |

**3. "Planned" is the clerk's final-revised docket, not the original plan.** Each agenda carries
`EventAgendaStatusName: Final-Revised` and `EventAgendaLastPublishedUTC` after the meeting started (2026-10-22's was
published 2026-10-23 18:50 UTC, 2026-10-08's the next day). The API keeps one version, so for past meetings the
original agenda is not recoverable from it. What it does keep: which rows are on the final agenda, which exist only in
the minutes (added), and each row's step. For future meetings the original plan can only be captured by
snapshotting agendas before the meeting (T-20). One caveat: I could see only one upcoming agenda (today's Council
meeting), and it was already marked Final-Revised, so I can't yet say how many days ahead a first version appears.

**4. Each matter's lifecycle can be rebuilt from the meetings' own item rows.** A matter's rows across meetings
(date, body, action) give introduction, referral, committee holds and advances, Council holds and the final vote.
The per-matter history endpoint exists too (11 rows for 260445: referred 05-07, Hold on Agenda 05-12, Adv and Do
Pass as Cmte Sub 05-19, then Held on Docket 05-21, 06-11, 07-02 ...) but it needs one call per matter, which the
backfill does not require.

**5. History depth.** Council events with minutes in the API: 2020: 1, 2021: 8, 2022: 27, 2023: 36, 2024: 35,
2025: 34, 2026 so far: 31. About 170 meetings with minutes from 2021 on (earlier years have none). A spot check of
the 2022-01-06 meeting shows 69 item rows with agenda sequences, minutes sequences and actions, so the structured
comparison reaches back to at least early 2022. Committee meetings are similar but smaller; Council first.

**6. Of the 47 matters on the 2026-10-22 agenda, 11 had been held at least once and 43 first appeared in October.**
That is the kind of fact a "what keeps getting deferred" view is built from, and it is plain counting.

## What gets computed (code only, no model)

For each meeting, each matter on it falls into one class, from the row patterns above:

| Class | Rule |
|---|---|
| **Carried through** | On the agenda; the minutes record a final action (Passed, Adopted, Failed, Adopted as Substituted ...). |
| **Advanced on the floor** | On the agenda at an earlier step (introduce, consider, amend); minutes-only rows then advance it and it moves on the same day. A separate flag marks an **ordinance decided on its first appearance**, the case that really skips the usual path (introduce, committee, return); resolutions are excluded because honoring someone or recognizing a month is routinely adopted the day it appears. |
| **Introduced** | The matter's first appearance, ending introduced or referred. The normal start of a matter, not a deferral. |
| **Deferred** | Final action is Held on Docket, Hold on Agenda or Re-referred, or referred when the matter had been seen before. With **how many times it has been held before** (from the matter's rows at earlier meetings). |
| **Added at the meeting** | The matter has no row with an agenda sequence at this meeting. |
| **On the agenda, no minutes row** | Agenda row with no minutes row for that matter at all. None seen in the four meetings; reported if it happens. |
| **Receive and file / communications** | Listed separately; they aren't decisions. |

Everything on the comparison page that is a count, a class, a date, an action or a "held N times" comes from those rows.
"Forgotten" is a loaded word and a judgement; the page shows the data (held 9 times since May 7) and does not label anything
forgotten.

## Results on the four saved meetings (T-16, `pipeline/compare.py`)

Computed from the city's rows only: no model, 0 tokens, no generated text. 35 meetings of rows since April were used
for the "held before" counts.

| Meeting | Matters | Carried through | Advanced on the floor | Deferred | Introduced | Added at the meeting | On agenda, no minutes row | Receive and file | Matters held at least once before |
|---|---|---|---|---|---|---|---|---|---|
| Council 2026-10-22 | 47 | 27 | 2 | 1 | 15 | 0 | 0 | 2 | 6 |
| Council 2026-10-08 | 34 | 7 | 2 | 2 | 23 | 0 | 0 | 0 | 5 |
| Council 2026-10-01 | 31 | 18 | 2 | 0 | 10 | 1 | 0 | 0 | 4 |
| FGPS committee 2026-09-08 | 5 | 3 | 0 | 2 | 0 | 0 | 0 | 0 | 2 |

The items behind the numbers:

| Class | Matters | Detail |
|---|---|---|
| Advanced on the floor, first appearance (the real skips) | 260946, 260947 (Oct 22) | New ordinances: planned as Move to Consider / Move To Introduce, then Move to Advance and Passed the same day. |
| Advanced on the floor, already seen | 260888, 260889 (Oct 8); two on Oct 1 | Committee substitutes seen at 2 earlier meetings; amended, advanced and passed. Not skipping anything. |
| Added at the meeting | 260850 (Oct 1) | A reconsideration with no agenda row at all: Move to Reconsider, Move to Advance, Passed. The only one in the four meetings. |
| Deferred, held N times | 260445 (Oct 22): **held 8 times before**, first seen 2026-05-07 (168 days) | Held 8 times before Oct 22: a committee Hold on Agenda on 05-12, then Held on Docket on 05-21, 06-11, 07-02, 07-09, 08-13, 09-10 and 10-08; held again on 10-22. The city's own history endpoint counts the same 9 holds in total. Held 7 times before Oct 8. |
| Held, then passed | 260563 (Oct 8): held 6 times before it passed; 260705 held 3; 260808 held 2 | |
| Committee deferrals | 260729 (held once before), 260834 (Sept 8) | Hold on Agenda. |

**What surprised me:**
1. **"Added at the meeting" is rare.** One matter in four meetings. My first count of minutes-only rows (6, 7 and 11 per
   meeting) overstated it by a wide margin, because a matter has one row per step: an item that was introduced and then
   advanced has minutes-only rows without being a late addition. Count matters, not rows.
2. **Nothing planned went missing from the minutes.** Zero agenda items without a minutes row in all four. The "forgotten"
   signal in this data is not "dropped" but "held again and again": 260445 has sat on the docket since May.
3. **Most agenda items are not decisions.** 15, 23 and 10 of each Council meeting's matters are newly introduced and referred.
   A comparison page should separate decisions from introductions or the counts mislead.
4. **Most skipped-the-usual-path cases are not what they look like.** Of six "advanced on the floor" matters at the three Council
   meetings, only two (260946, 260947) were first-appearance ordinances decided the same day; the other four had been seen at earlier
   meetings (260888 and 260889 are amended committee substitutes). Hence the extra flag.
5. **The city edits records after the fact.** When I refreshed a fixture today, one item's title (260943) had been shortened
   since I first saved it. That is a small proof that only a snapshot taken at the time preserves what was said then.

## Which claims would be code-verified and which model-written

| On the page | Source | Verified how |
|---|---|---|
| Which items were planned, carried through, advanced, deferred, added | API rows | Computed by code from the city's own fields. |
| Counts, percentages, dates, "held N times", time from introduction to passage | API rows | Computed by code. |
| Each item's link to the official record | API / Legistar | Taken from the record. |
| A **plain-language label** for each item ("Sets aside $1,000,000 for a playground at Barry Road Park") | Model, from the item's own title | Checked by the fact-checker against the title text, plus the existing number and quote checks. Only labels that pass are shown; the rest show the official title, trimmed. |
| **Topic** of an item | Keyword rules (code) first; model only for what the rules leave as "other" | Rules are deterministic. Model tags only where a sample shows they add value (below). |
| A one-paragraph **narrative** about a trend ("held more often in 2025") | Model, from a computed table | Every number in it must equal a number in the table (code check); the fact-checker reads the sentence against the table. Anything that fails is dropped and the table stands alone. |

The rule behind the table: an agenda is a plan and never an outcome. Any agenda-derived sentence the model writes
may say "scheduled" or "listed", never "passed" or "approved" (T-3 enforces this in code).

## Backfill and what it costs

| Part | How | Tokens |
|---|---|---|
| Fetch ~170 meetings' events and item rows (2021 on) | 2 API calls per meeting, about 340 calls, at the pipeline's polite 0.5 s pace: a few minutes | **0** |
| Classify every matter at every meeting; rebuild every matter's lifecycle | Code only | **0** |
| Topic for every matter | Keyword rules | **0** |
| Check the keyword rules against a model on a **sample** of 300 item titles | One-off, to measure the rules' accuracy | about **55k** (titles average 499 characters, ~143 tokens: 300 x 143 in + labels out + overhead) |
| Plain-language labels for one Council meeting (~47 matters) | Nightly, with a fact-check pass | about **21k** per meeting |
| Model tagging of **every** past matter | Not proposed | about **1.1 million** (~6,800 matters x ~143 tokens in, ~25 out) |

So the backfill and the trends need no plan usage; the validation sample is about 55k; the nightly labels add about
21k to a Council night. Anything that would take the total past about 150k (tagging the residual "other" items, if the
sample shows the rules are weak) will be put to the user first.

## The pages

1. **One meeting, planned versus happened.** A table of the classes above with counts first, then each item with its
   class, its action, its label and a link to the city's record. A line states that "planned" means the clerk's
   final-revised docket.
2. **Trends.** Per quarter and per topic: items planned, share carried through, share deferred, how many were held
   more than once, time from introduction to passage, share advanced on the floor. Tables and small charts from the
   computed data; an optional checked narrative.

## T-20: agenda snapshots, built as a dry run (not scheduled)

`scripts/snapshot_agendas.py` saves each upcoming agenda (Council and the three standing committees) as one file per
version, `DIR/<event_id>/<fetched-at>.json`, with the item rows, the agenda status and its publish time. A version
identical to the latest saved one is skipped, so a nightly run keeps every real revision and nothing else; a snapshot is
never overwritten. It is dry-run unless `--save` is passed, makes API calls only, and is **not scheduled**. Seven tests use a
fake API.

Dry run against the live API on 2026-10-29 for the next 14 days: one meeting had an agenda, today's Council meeting (59
rows, 57 on the agenda), already `Final-Revised` and published at 21:10 UTC, after the 2 PM start. Nothing is published ahead of
the others yet, so I can't say how many days before a meeting a first version appears; that is what a few weeks of
snapshots will show. When it is scheduled it belongs in the nightly's run job (it needs no token) with the snapshots kept on
the data branch under `snapshots/`, which is a workflow change the user has not approved.

## Tickets

| | What | Uses plan usage |
|---|---|---|
| T-3 | The agenda guard: an agenda-derived claim can't state an outcome. **Done.** | no |
| T-16 | The matcher: classify every matter at a meeting from the API rows, lifecycles across meetings. **Done.** | no |
| T-17 | The one-meeting comparison page | small (labels) |
| T-18 | The backfill: ~170 meetings of structured rows, cached on the data branch | no |
| T-19 | The trends page and the keyword topic rules, with a sampled check against the model | about 55k, once |
| T-20 | Snapshot upcoming agendas each night so the original plan is kept before it is revised. **Script and dry run done; not scheduled.** | no |

Order: T-3 and T-16 first (free, and they decide whether the idea holds up on real meetings), then T-18, T-17, T-20,
T-19. Nothing is added to the nightly or published until the matcher is validated on the saved meetings and the user has
seen a comparison.
