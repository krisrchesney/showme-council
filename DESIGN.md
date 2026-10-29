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
| Orchestrator | `pipeline/run.py` | `ingest`, `estimate`, `process`, `nightly`, `build-site`. Budget caps live here. |

Each agent stage is one headless Claude Code call (`pipeline/agents.py`):

```
claude -p "<task>" --agents <built from .claude/agents/*.md> --agent extractor
       --output-format json --json-schema schemas/extractor.json
       --tools "" --max-budget-usd <what's left> --no-session-persistence
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
| 3 | `numbers_in_quote` | code | A number in the statement or `amount_usd` isn't in the quote. The meeting date's parts are allowed, and so is the claim's own matter number when check 4 proves it by position. |
| 4 | `matter_block` | code | The quote sits inside a *different* agenda item's text than the matter number the claim names. Legistar minutes print an item's number a few lines after its description, so a correct quote often can't contain it. The blocks are found by locating each API item's description in the source. If the claimed item can't be located, this check is skipped, not failed. |
| 5 | `api_agrees` | code | The claim says "passed" but the city's own record for that matter number says "referred" (or the other way round). Skipped when the API has no record. |
| 6 | verdict | fact-checker agent | The verdict is anything but `SUPPORTED` (`PARTIAL` = one detail wrong, `UNSUPPORTED` = not in the source). |

A summary **sentence** is published only if the fact-checker marks it `FAITHFUL`
to the claims it cites **and** every one of those claims was accepted. A faithful
sentence about a rejected claim is still dropped. The headline is checked as one
extra sentence; if it fails, the page uses a plain "Council minutes, 2026-10-22" title.

**Metrics per document** (in `report.json`, `metrics.jsonl`, and shown on the site):
- `claim_pass_rate` = accepted / extracted, plus counts for each rejection reason
- `sentence_pass_rate` = published / written
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
the fact-checker itself is right. T-5 adds planted errors to real runs to
measure the checker's catch rate.

## Schedule: GitHub Actions vs. a local scheduled task

Checked against the current docs (code.claude.com/docs/en/github-actions and
/headless, 2026-10-29).

| | GitHub Actions cron (recommended) | Windows Task Scheduler on this PC |
|---|---|---|
| Runs when the PC is off | Yes | No |
| Auth (chosen: **subscription**) | Repo secret `CLAUDE_CODE_OAUTH_TOKEN`, a long-lived token from `claude setup-token`, billed to your Claude plan | `claude auth login` with your Claude plan |
| Reproducible | Same flags every run; hooks are skipped via `SHOWME_PIPELINE=1`, MCP via `--strict-mcp-config`. `--bare` is **not** used: bare mode never reads OAuth, so it only works with an API key | Depends on local state |
| Publishing | `actions/deploy-pages` in the same job | Needs a `git push` from this PC |
| Cost of the runner | Free for a public repo | Free |
| Gotchas | Cron runs only from the default branch; GitHub turns schedules off after 60 days without repo activity (the nightly data commit counts as activity); cron times are UTC and can start late | PC asleep = missed night |

Why the workflow calls the `claude` CLI directly instead of `anthropics/claude-code-action`:
the action runs one prompt, but this pipeline is three schema-checked calls with
code in between, and Python owns that loop. The action fits "do this task in my
repo", not "call a model three times inside my program".

**Auth decision (2026-10-29): subscription, not API billing.** Locally the CLI
is logged in with your plan. In Actions, run `claude setup-token` once on this PC
and store its output under repo Settings → Secrets and variables → Actions →
New repository secret as `CLAUDE_CODE_OAUTH_TOKEN`. The workflow reads it only as
`${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`; it never goes in a file. The token is tied
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

## Cost per night

**With a subscription there is no per-token bill.** Runs draw on your plan's usage
limits, the same pool your interactive Claude Code sessions use. So the real
constraint is usage headroom, not dollars:
- Tokens per document (below) are what each night takes from the plan: about
  75k per document (~56k in, ~18k out incl. thinking), ~5 documents a week, so
  roughly 375k tokens a week. `estimate` prints both tokens and API-price dollars.
- Schedule the run at night (07:30 UTC) so it doesn't compete with daytime sessions.
- If a run hits a usage limit, the CLI returns an error, the document is marked
  `error`, and it retries the next night (`MAX_TRIES = 3`). Nothing half-finished
  is published.
- `--max-budget-usd` and the per-document and per-night caps stay. Under a
  subscription they act on Claude Code's *estimated* cost, so they still stop a
  runaway loop. The `total_cost_usd` in `report.json` is the API-price equivalent,
  not a charge.

The API-price equivalent is still useful as a size measure, and it's what an
API-key fork would pay. Prices: Opus 5.5 $4 / $20 per million input / output
tokens; Sonnet 5.5 $2 / $10; Haiku 5.5 $0.10 / $0.50. Agents default to **Sonnet 5.5**
(`model:` in each `.md`; see "Model policy").

One KC Council minutes document (the 2026-10-22 fixture: 28 pages, about 12.6k
tokens of text). `python -m pipeline.run estimate <doc>` gives:

| Stage | In (tokens) | Out incl. thinking | Opus 5.5 (the estimate for an escalated run) |
|---|---|---|---|
| extractor | ~19k | ~9k | $0.26 |
| summarizer | ~10k | ~2.5k | $0.09 |
| fact-checker | ~27k | ~6k | $0.23 |
| **per document** | | | **≈ $0.57** (Sonnet 5.5: ≈ $0.29) |

**Measured, one real run** (Opus 5.5, before the model policy changed): 62.5k tokens in and
13.7k out across the three calls, about 2 minutes, $0.77 API-equivalent: extractor $0.34
(60 s), summarizer $0.09, fact-checker $0.34. The estimate said 55k in / 17.5k out / $0.57,
so it was low on dollars (~35%), mostly because each call writes the document into the
prompt cache. No Sonnet run has been measured yet; the Sonnet figure above is the estimate.

Volume with the chosen bodies (Council + 3 standing committees): about 5 new
documents a week (Council agenda and minutes, committee agendas). That's
**about $0.20 a night, or $6 a month, in API-price terms on Sonnet 5.5** (double that if
every document were escalated to Opus 5.5), and $0 billed on the subscription. Haiku 5.5
would be cheaper still and is untested for quality. Committee agendas are shorter than the fixture, so these numbers are
on the high side. The first real runs replace them: every run records Claude
Code's reported `total_cost_usd` per stage in `report.json`.

Hard caps: `--max-budget-usd` on every call (the stage gets what's left of the
document's cap), `$1.50` per document, `$4.00` per night (`nightly --max-usd`).
Hitting the nightly cap leaves the remaining documents for tomorrow. GitHub runner
minutes: free for a public repo. Actual dollars billed under the chosen setup: $0
beyond the existing Claude plan.

## Model policy

Default to **Sonnet 5.5** (`claude-sonnet-5-5`) for the three pipeline agents and for
the planner and reviewer dev agents. Move to a bigger model only when the user
asks for it, never automatically. That's a user-set rule, not a measurement: it
needs a first Sonnet run to confirm quality is acceptable.

How escalation works, with no silent model switching:
- The pipeline stops a document with `status: needs_model` and prints
  `this may need Opus: <why>. Rerun with: python -m pipeline.run process <doc> --model claude-opus-5-5`
  when, on the default model, (a) an agent returns nothing that parses against its
  schema, or (b) the fact-checker gives no verdict for more than 10% of the claims.
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
