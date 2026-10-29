# Tasks

The shared backlog. Agents coordinate through this file and git. Take one Ready
ticket, move it to In progress with your branch name, and touch only what it Owns.
"Uses plan usage" means verifying it calls Claude on the subscription; give the heads-up first (CLAUDE.md).

Template:

    ### T-<n>: <title>
    Status: Ready
    Owns: <files / functions this ticket may change>
    Blocked by: none | T-x
    Uses plan usage: no | yes (~tokens)
    Why: <one line>
    Done when:
    - [ ] <checkable without asking anyone>

## Ready

### T-1: Turn on the nightly GitHub Actions run
Status: Ready (needs the user's OK: GitHub repo, CLAUDE_CODE_OAUTH_TOKEN secret, Pages)
Owns: .github/workflows/nightly.yml; DESIGN.md "State between nights" paragraph
Blocked by: none
Uses plan usage: yes (~75k tokens per document, ~5 documents a week)
Auth is decided (user, 2026-10-29): a subscription token from `claude setup-token`, stored as the
repo secret `CLAUDE_CODE_OAUTH_TOKEN`. It draws on the same plan usage; an API key would bill per token,
so never use one. The user generates the token themselves once the repo exists. The token must never go in
a file, a commit, a log or chat: don't ask for it, and don't paste it anywhere.
Why: The workflow is written but has no cron trigger, no state commit-back and no Pages deploy.
Done when:
- [ ] `schedule: cron` added (e.g. 07:30 UTC = 2:30 AM CDT), plus `workflow_dispatch`
- [ ] Job commits data/state.json, data/published/, data/metrics.jsonl back (main or a `data` branch, chosen and written down in DESIGN.md)
- [ ] Site is deployed with actions/upload-pages-artifact + actions/deploy-pages
- [ ] `concurrency` set so two nights never overlap; job `timeout-minutes` set
- [ ] The pinned `@anthropic-ai/claude-code` version in the workflow exists on npm (it was copied from the local 2.1.299 build)
- [ ] Auth is `CLAUDE_CODE_OAUTH_TOKEN` only (`${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`); the workflow sets no `ANTHROPIC_API_KEY` and no `SHOWME_BARE`
- [ ] The ticket notes tell the user how to add the secret (repo Settings > Secrets and variables > Actions > New repository secret) without the builder ever seeing the value
- [ ] A calendar reminder (or README note) to renew the token before it expires after one year
- [ ] One manual `workflow_dispatch` run is green and the Pages URL loads

### T-2: CI check on every push
Status: Ready
Owns: .github/workflows/check.yml (new); README.md badge line
Blocked by: none
Uses plan usage: no
Why: The Stop hook guards local sessions; CI should guard pushes and PRs the same way.
Done when:
- [ ] Workflow runs `pip install -r requirements.txt` then `python scripts/check.py` on push and pull_request, Python 3.12
- [ ] No secrets are used by this workflow
- [ ] README has a status badge for it

### T-3: Agendas must never read as decisions
Status: Ready
Owns: pipeline/verify.py `code_checks()` (new `agenda_tense` check); tests/test_verify.py new class; tests/fixtures/kansascity/ agenda text (via scripts/refresh_fixture.py --agenda)
Blocked by: none
Uses plan usage: no
Why: An agenda says what's planned. A claim like "passed" on an agenda is wrong even if the quote exists.
Done when:
- [ ] For `kind == "agenda"`, a claim with outcome passed/adopted/failed, or "passed"/"approved" in the statement, is rejected with reason `agenda_states_outcome`
- [ ] The KC agenda PDF text for event 19561 is in the fixture, so the offline nightly test no longer logs an ingest error for it
- [ ] Tests cover both a rejected and an allowed ("is scheduled for a vote") agenda claim

### T-4: Add Columbia as a second Legistar source
Status: Ready
Owns: pipeline/sources/__init__.py `get_source`; `COMO_BODIES` constant in pipeline/sources/legistar.py; tests/fixtures/gocolumbiamo/ (new); tests/test_columbia.py (new)
Blocked by: none
Uses plan usage: no (the fixture is free to download)
Why: Proves the adapter isn't hard-wired to Kansas City. Same API, client `gocolumbiamo`.
Done when:
- [ ] `get_source("columbia")` returns a LegistarSource with prefix `como` and City Council bodies
- [ ] A real cached Columbia meeting fixture (made with refresh_fixture.py, given a `--client` flag) passes the same list/fetch tests as KC
- [ ] The site footer credit names the source city per document, not always Kansas City

### T-5: Measure the fact-checker's catch rate with planted errors
Status: Ready
Owns: pipeline/canary.py (new); one call in pipeline/run.py `process()` after the fact-checker stage; tests/test_canary.py (new)
Blocked by: none
Uses plan usage: yes (adds ~10% to the fact-checker stage)
Why: The pass rate says how much survives; it doesn't say whether the checker would catch a bad claim. Planted errors do.
Done when:
- [ ] For each document, 2 accepted-looking claims are copied and changed in ways code can't catch (outcome word flipped, body name swapped) and marked `canary: true`
- [ ] Canaries go through the fact-checker with the real claims, are never published, and `report.json` gets `canary_caught / canary_total`
- [ ] The site's index shows the running catch rate next to the pass rate
- [ ] Offline test with stub verdicts proves canaries can't reach data/published

### T-6: St. Charles County agendas (CivicPlus AgendaCenter)
Status: Ready
Owns: pipeline/sources/civicplus.py (new); tests/fixtures/stcharles/ (new); tests/test_civicplus.py (new); one line in pipeline/sources/__init__.py
Blocked by: T-4 (both add a line to `get_source`)
Uses plan usage: no
Why: A source with no API. County Council agendas list each purchase as vendor / amount / term.
Done when:
- [ ] Lists County Council (catID=1) documents via POST /AgendaCenter/UpdateCategoryList and downloads /AgendaCenter/ViewFile/Agenda/_MMDDYYYY-ID
- [ ] Never requests /RSS.aspx (disallowed in robots.txt since 2026-10-20); one request per second at most
- [ ] Minutes are skipped with a clear "scanned, needs OCR" error, not sent to agents empty (pdftext already raises)
- [ ] `api_items` is `[]`, so api_check reports `unchecked`, and tests prove it

### T-7: Show the roll call from the city's own record
Status: Ready
Owns: pipeline/site.py `doc_page()`; the `data/published/<doc>.json` dict built in pipeline/run.py `process()` (add a `votes` field)
Blocked by: none
Uses plan usage: no
Why: Per-member votes come straight from the API: exact, free, and no model involved.
Done when:
- [ ] For each accepted vote claim with a matter number, the page shows who voted Aye/Nay/Excused, taken from api_items, not from agent output
- [ ] Labelled "From the city's vote record" so readers can tell it from AI text
- [ ] Offline test checks the 260919 roll call renders with 12 Ayes and Robinson excused

### T-8: Coverage metric from the city's own record, and a "too few facts" stop
Status: Ready
Owns: pipeline/verify.py (new `coverage()`); the report fields built in pipeline/run.py `finalize()`; pipeline/site.py index stats; one new stop condition in `process()`; tests/test_coverage.py (new)
Blocked by: none
Uses plan usage: no
Why: The pass rate says how much of what was extracted survived, not how much of the meeting was covered. The Sonnet comparison (docs/MODEL-COMPARISON.md) produced 7 facts from a meeting with 29 recorded votes and nothing in the pipeline noticed.
Done when:
- [ ] `coverage` = share of API items with a recorded pass/fail (minutes only) that have at least one accepted fact; stored in report.json and metrics.jsonl and shown on the index next to the pass rate
- [ ] Offline test: Opus's saved facts give 19 of 29, Sonnet's give 4 of 29 (fixtures copied into tests/fixtures/)
- [ ] On the default model, coverage under a threshold written in verify.py (suggest 40%) stops the document with `this may need Opus: only N of M voted items covered`; under an explicit Opus run it only reports
- [ ] The threshold is not lowered to make a run pass (CLAUDE.md "Never")

### T-9: Extractor prompt for coverage, tested on Sonnet
Status: Ready
Owns: .claude/agents/extractor.md
Blocked by: T-8 (to measure the result)
Uses plan usage: yes (one real run, ~60-75k tokens; give the heads-up first)
Why: Sonnet read "precision matters far more than coverage" as "write few facts". Opus did not.
Done when:
- [ ] The prompt asks for one fact per voted item and per money item, not a sample, while keeping the quote and number rules
- [ ] One Sonnet run on kc-19561-minutes into experiments/ (not the published page) reaches coverage within 10 points of Opus's 19/29 with a claim pass rate no worse than 80%, or the ticket reports it didn't and recommends the extractor-only Opus option (ask the user first)
- [ ] The result is added to docs/MODEL-COMPARISON.md

## In progress

## Review

## Done
- T-0: Scaffold: KC Legistar ingester with offline fixture, three pipeline agents, code checks, site builder, check script + Stop hook (2026-10-29)
