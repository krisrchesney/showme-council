# showme-council design

Every night, a pipeline pulls new Kansas City Council and committee records, has
three Claude agents turn them into fact-checked plain-language summaries, and
publishes the result as a static site. Nothing reaches the site unless code
**and** a separate fact-checking agent both find it in the source text.

Source choice (researched 2026-10-29, links opened live): Kansas City's Legistar
Web API is a free JSON feed with no key, and it has outcomes and per-member roll
calls. Columbia uses the same API (T-4). St. Charles County publishes PDFs only,
and its minutes are scanned images (T-6). St. Louis's robots.txt blocks the bill
pages, so it was dropped.

## Pipeline stages and handoff files

Stages talk only through files. Any stage can be re-run, inspected, or swapped
on its own.

```
             Legistar API (JSON) + agenda/minutes PDF
                          │
 1. ingest (code)         ▼   data/raw/<doc>/meta.json, source.txt, api_items.json
                          │
 2. extractor (agent)     ▼   data/work/<doc>/facts.json        claims, each with a verbatim quote
                          │
 3. code checks           ▼   data/work/<doc>/checks.json       quote found? numbers in quote? API agrees?
                          │
 4. summarizer (agent)    ▼   data/work/<doc>/summary.json      sentences that cite claim ids
                          │   (sees claims only, never the source)
 5. fact-checker (agent)  ▼   data/work/<doc>/verdicts.json     per-claim and per-sentence verdicts
                          │
 6. decide (code)         ▼   data/work/<doc>/report.json       accepted / rejected + reasons
                          │   data/published/<doc>.json         accepted claims and sentences ONLY
                          │   data/metrics.jsonl                one line per document
 7. build-site (code)     ▼   site/index.html, site/doc/<doc>.html
```

| Piece | File | What it does |
|---|---|---|
| Source adapter | `pipeline/sources/legistar.py` | Lists meetings for the chosen bodies, downloads the PDF, extracts text with page markers, and attaches API items (matter number, action, pass/fail, roll call). Live or fixture transport. |
| Extractor | `.claude/agents/extractor.md` | Source text → up to 40 claims (`statement`, verbatim `quote`, `page`, `matter_file`, `outcome`, `amount_usd`). Told precision beats coverage. |
| Code checks | `pipeline/verify.py` | Deterministic and free. See scoring below. |
| Summarizer | `.claude/agents/summarizer.md` | Claims → headline + 3-8 sentences, each citing claim ids. It never sees the document, so it can only restate claims. |
| Fact-checker | `.claude/agents/fact-checker.md` | Gets the full source, the claims, the code results and the sentences. Assumes the others made mistakes. |
| Decide | `pipeline/verify.py: decide()` | Combines the code checks and the verdicts. It's the only code that writes `data/published/`. |
| Site | `pipeline/site.py` | Static HTML: each fact links to its quote, page and the official PDF, and every page shows its own pass/reject counts. |
| Orchestrator | `pipeline/run.py` | `ingest`, `estimate`, `process`, `redecide`, `nightly`, `build-site`. Runaway-loop caps live here. |

Each agent stage is one headless Claude Code call (`pipeline/agents.py`):

```
claude -p "<task>" --agents <built from .claude/agents/*.md> --agent extractor
       --output-format json --json-schema schemas/extractor.json
       --tools "" --max-budget-usd <loop cap> --no-session-persistence
       --strict-mcp-config --disable-slash-commands --effort medium
```

The payload goes in on stdin. `--json-schema` makes the output machine-checkable.
`--tools ""` means an agent can only read what it's given and return JSON, so an
instruction hidden in a PDF has nothing to act with. The `.md` agent files are the
single source of truth: a person can run the same agent by hand, and the pipeline
builds its `--agents` JSON from them.

## How the fact-checker scores support (the metric)

A claim is **accepted** only if all six checks pass:

| # | Check | Who | Rejects when |
|---|---|---|---|
| 1 | `quote_found` | code | The normalized quote isn't in the source exactly and no window is ≥ 0.92 similar (`FUZZY_MIN`, which allows for PDF spacing noise). |
| 2 | `quote_length` | code | The quote is under 20 characters, too short to prove anything ("Passed"). |
| 3 | `numbers_in_quote` | code | A number in the statement or `amount_usd` isn't in the quote. The meeting date's parts are allowed, so is the claim's own matter number when check 4 proves it by position, and so are ordinals in the statement ("63rd Street" is a name; "November 5th" in a quote still supports "November 5"). |
| 4 | `matter_block` | code | The quote occurs only inside *other* agenda items' text than the matter number the claim names. Legistar minutes print an item's number a few lines after its description, so a correct quote often can't contain it. The blocks are found by locating each API item's description in the source. Any occurrence of the quote inside the claimed item's own block counts: boilerplate such as "A motion was made that this Ordinance be Passed" repeats under every passed item, so looking only at its first occurrence blames the wrong item (found by the Sonnet comparison). A boilerplate quote still can't back a claim about an item whose block lacks it. If the claimed item can't be located, the check is skipped, not failed. |
| 5 | `api_agrees` | code | The claim says "passed" but the city's own record for that matter number says "referred" (or any other pairing that doesn't match). Compared with the city's own wording: "held" matches Held on Docket / Hold on Agenda / Held in Committee, "referred" matches Re-referred, "advanced" matches Adv and Do Pass / Move to Advance, and "Adv and Do Pass" is not "passed". Skipped when the API has no record or the outcome is "other". |
| 6 | verdict | fact-checker agent | The verdict is anything but `SUPPORTED` (`PARTIAL` = one detail wrong, `UNSUPPORTED` = not in the source). |

A summary **sentence** is published only if the fact-checker marks it `FAITHFUL`
to the claims it cites **and** every one of those claims was accepted. A faithful
sentence about a rejected claim is still dropped. The headline is checked as one
extra sentence; if it fails, the page uses a plain "Council minutes, 2026-10-22" title.

The headline is held to the same rule as the sentences: it is published only if the checker marks
it FAITHFUL **and every claim the summary cited was accepted** (a rejected fact can't ride in on a
headline). That is conservative: one dropped sentence sends the page back to a plain title until T-10
gives the headline its own claim list.

**Metrics per document** (in `report.json`, `metrics.jsonl`, and shown on the site):
- `claim_pass_rate` = accepted / extracted, plus counts for each rejection reason
- `sentence_pass_rate` = published / written
- `coverage` = of the agenda items the city's API records a pass/fail for (minutes only), how many
  have at least one **accepted** fact. The pass rate says how much of what was extracted survived;
  coverage says how much of the meeting was extracted at all, measured against the city's own
  record. On the 2026-10-22 minutes: Opus 19 of 29 (66%), Sonnet with the first prompt 4 of 29 (14%),
  Sonnet with the coverage prompt 26 of 29 (90%).
- `code_vs_checker`: how often code and the LLM checker agree. Disagreements are
  the interesting cases. Code catches a wrong number reliably; only the agent
  catches "unanimously" when one member was excused.

Why two layers: the model that does the work never judges its own work. Code
checks are cheap and can't be talked out of a result. The agent catches meaning
errors that string matching can't see. The stub fixture plants one error of each
kind, and `tests/test_verify.py` proves each is caught for the right reason.

**What the first real run showed** (2026-10-29, KC Council minutes of 2026-10-22,
37 claims, run on Opus 5.5 before the Sonnet default): the first scoring pass
rejected 19 claims for "number not in quote", and the fact-checker had marked all 19
SUPPORTED. The checker was right and my code check was wrong: it demanded the matter
number (260885) inside the quote, and the minutes print that number after the
description. Check 4 replaced that with a positional proof. Re-scoring the saved
agent outputs with `python -m pipeline.run redecide <doc>` (free, no model call)
took the pass rate from 49% to 86% (32 of 37). The 5 remaining rejections are
correct under the rules: a claim stating "Fund No. 2220" or "FY 2026-27" whose
quote doesn't contain that number (3), an unlocated item whose number isn't in
the quote (1), and the checker catching "acknowledges" for an ordinance that was
only introduced (1). Lesson: when code and the checker disagree, read the
disagreements before trusting either.

What the metric does not prove: recall (facts the extractor missed), or that
the fact-checker itself is right. For the checker, each run now plants a few deliberately false
claims in its input (`pipeline/canary.py`): outcome flipped, a false "unanimously", a swapped
councilmember, a wrong body. Their counts show on the site and in `report.json`; the fakes are
split off before `decide()` and never published. First measurement (docs/MODEL-COMPARISON.md,
Test 3): 10 of 10 caught for the right reasons, 0 of 118 real claims flagged. A small sample of easy fakes;
T-14 makes them subtler.

## Schedule: GitHub Actions vs. a local scheduled task

Checked against the current docs (code.claude.com/docs/en/github-actions and
/headless, 2026-10-29).

| | GitHub Actions cron (recommended) | Windows Task Scheduler on this PC |
|---|---|---|
| Runs when the PC is off | Yes | No |
| Auth (chosen: **subscription**) | Repo secret `CLAUDE_CODE_OAUTH_TOKEN`, a long-lived token from `claude setup-token`; draws on your Claude plan's usage | `claude auth login` with your Claude plan |
| Reproducible | Same flags every run; hooks are skipped via `SHOWME_PIPELINE=1`, MCP via `--strict-mcp-config`. `--bare` is **not** used: bare mode never reads OAuth, so it only works with an API key | Depends on local state |
| Publishing | `actions/deploy-pages` in the same job | Needs a `git push` from this PC |
| Runner minutes | Free for a public repo | n/a |
| Gotchas | Cron runs only from the default branch; GitHub turns schedules off after 60 days without repo activity (the nightly data commit counts as activity); cron times are UTC and can start late | PC asleep = missed night |

Why the workflow calls the `claude` CLI directly instead of `anthropics/claude-code-action`:
the action runs one prompt, but this pipeline is three schema-checked calls with
code in between, and Python owns that loop. The action fits "do this task in my
repo", not "call a model three times inside my program".

**Auth decision (2026-10-29): subscription, not API key.** (An API key bills per token. You chose the subscription token on 2026-10-29; an API key is never used without you.) Locally the CLI
is logged in with your plan. In Actions, you run `claude setup-token` yourself once
the repo exists and store its output under repo Settings → Secrets and variables → Actions →
New repository secret as `CLAUDE_CODE_OAUTH_TOKEN`. The workflow reads it only as
`${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`; it never goes in a file, commit, log or chat (you generate it and paste it into GitHub yourself). The token is tied
to your personal subscription, which is fine for a personal repo (the docs suggest
an API key only for secrets shared across an organization). The token lasts one
year, so renewing it is a yearly chore (T-1). If `ANTHROPIC_API_KEY` is also set,
it outranks the token and billing silently moves to the API, so the workflow never
sets both. The API-key path still
works for anyone forking: set `ANTHROPIC_API_KEY` and `SHOWME_BARE=1`. `.github/workflows/nightly.yml` is written but has
**no cron trigger yet**; enabling it is T-1 and needs your OK.

**State between nights.** `data/state.json` (what's done or failed),
`data/published/` and `data/metrics.jsonl` are the record and get committed.
`data/raw/`, `data/work/` and `site/` are rebuilt each night and are gitignored.
In Actions, the job commits the record back (T-1 decides main vs. a `data` branch).

## Usage per night

This runs on your Claude Max subscription. Nothing is billed per token, so the thing to
watch is how much of the plan's usage window a night takes. Every run records, per stage
and in total: tokens in and out, turns, model, and wall time (`report.json` →
`usage`; the front page of the site shows pass rates, not usage).

**Measured, one real run** (KC Council minutes of 2026-10-22, Opus 5.5, before the
model policy changed to Sonnet): 62.5k tokens in and 13.7k out over three calls
(extractor, summarizer, fact-checker; 2 turns each), about 2 minutes of wall time
(60 s, 21 s, 35 s). `python -m pipeline.run estimate <doc>` had predicted 55k in and
17.5k out: within 5% on total tokens (input 12% low, output 28% high). No Sonnet run has
been measured yet.

**Expected per night:** about 5 new documents a week with the chosen bodies (Council
agenda and minutes, committee agendas), or roughly 75k tokens per document and
**375k tokens a week**, averaging a bit over 50k a night. Committee agendas are shorter
than the fixture, so that is on the high side. The plan weights models differently, and
I don't know the weights, so expect a Sonnet night to take less of the window than an
Opus night but measure it before relying on that.

**The real limit is the plan's usage window,** the same pool your interactive Claude Code
sessions draw on. So:
- The nightly run is scheduled for 07:30 UTC (2:30 AM Central) so it doesn't compete
  with daytime sessions.
- If a run hits the limit, the CLI returns an error, the document is marked `error`, and
  it is retried the next night (`MAX_TRIES = 3`). Nothing half-finished is published.
- There is no dollar budget and no approval step. A heads-up before the first real run
  in a session (model, expected tokens) is all CLAUDE.md asks for.

**API-equivalent figures.** Claude Code also reports what it estimates the same tokens
would cost at API rates. The pipeline stores that as `api_equiv_usd`, only so models and
runs can be compared on one number. It's an estimate, not a charge. Rates used by
`estimate`, USD per million tokens in / out: Opus 5.5 4 / 20, Sonnet 5.5 2 / 10,
Haiku 5.5 0.10 / 0.50. For the measured run, Claude Code reported 0.77 API-equivalent
units against the 0.57 `estimate` gives, because each call writes the document into the
prompt cache. At those rates one document on Sonnet 5.5 comes to about half the Opus
figure for the same tokens (`estimate --model claude-sonnet-5-5` prints 0.29); that is an
estimate, not a measurement.

**Runaway-loop protection.** Each agent call gets `--max-budget-usd` set to what is left
of the document's cap, and `nightly --loop-cap` bounds the whole night (defaults 1.50 per
document and 4.00 per night). These are measured in API-equivalent units because that is
what the CLI can enforce. They are tripwires set several times above a normal run
(0.77 measured), so they stop a stuck loop and are not a spending limit. This CLI has no
`--max-turns` flag. The agents have no tools, so a call is 1 to 2 turns anyway.

## Model policy

Default to **Sonnet 5.5** (`claude-sonnet-5-5`) for the three pipeline agents and for
the planner and reviewer dev agents. Move to a bigger model only when the user
asks for it, never automatically. That's a user-set rule, not a measurement: it
was checked with a Sonnet run on one document (docs/MODEL-COMPARISON.md): with the coverage
prompt it matched Opus on accuracy and beat it on coverage. Treat that as one data point.

How escalation works, with no silent model switching:
- The pipeline stops a document with `status: needs_model` and prints
  `this may need Opus: <why>. Rerun with: python -m pipeline.run process <doc> --model claude-opus-5-5`
  when, on the default model, (a) an agent returns nothing that parses against its
  schema, (b) the fact-checker gives no verdict for more than 10% of the claims, or (c) coverage is
  under 40% (`COVERAGE_MIN`) for a meeting with at least 5 recorded votes: "only N of M voted items
  covered". (c) was added after Sonnet's first prompt produced 7 facts from a 29-vote meeting and no
  other rule noticed. The 40% floor sits between Opus (66%) and that run (14%); it is a first guess from
  one document. Stub runs skip (c), and an explicit Opus run reports coverage without stopping.
- Retrying the same model won't help, so nightly leaves a `needs_model` document
  alone until the user reruns it. Everything else keeps going.
- The user reruns that one document with `--model claude-opus-5-5`, which overrides
  all three agents. Under an explicit Opus run the same failures are plain errors,
  not another request to escalate.
- A low pass rate alone is not an escalation signal: rejections usually mean the
  checks are working. The report lists which model each stage used (`models`).

## Rules the design depends on

- Publish only our own summaries plus short cited quotes, and link to the
  official PDF. Don't re-host city PDFs. None of the sources has an open license.
  These are public records under Missouri's Sunshine Law (RSMo ch. 610).
- Every page says the content is unofficial and AI-written, and credits the source.
- No agent has tools. No agent output is published without `decide()`.
- Tests are offline: `tests/fixtures/kansascity/` is a real cached meeting, and
  `stub/` holds hand-written agent outputs with planted errors.
