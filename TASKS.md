# Tasks

The shared backlog. Agents coordinate through this file and git. Take one Ready
ticket, move it to In progress with your branch name, and touch only what it Owns.
"Paid run" means verifying it calls Claude, which uses the subscription's usage; ask the user first (CLAUDE.md).

Template:

    ### T-<n>: <title>
    Status: Ready
    Owns: <files / functions this ticket may change>
    Blocked by: none | T-x
    Paid run: no | yes (~$ estimate)
    Why: <one line>
    Done when:
    - [ ] <checkable without asking anyone>

## Ready

### T-1: Turn on the nightly GitHub Actions run
Status: Ready (needs the user's OK: GitHub repo, CLAUDE_CODE_OAUTH_TOKEN secret, Pages)
Owns: .github/workflows/nightly.yml; DESIGN.md "State between nights" paragraph
Blocked by: none
Paid run: yes, subscription usage (~75k tokens per document, ~5 documents a week; no API bill)
Why: The workflow is written but has no cron trigger, no state commit-back and no Pages deploy.
Done when:
- [ ] `schedule: cron` added (e.g. 07:30 UTC = 2:30 AM CDT), plus `workflow_dispatch`
- [ ] Job commits data/state.json, data/published/, data/metrics.jsonl back (main or a `data` branch, chosen and written down in DESIGN.md)
- [ ] Site is deployed with actions/upload-pages-artifact + actions/deploy-pages
- [ ] `concurrency` set so two nights never overlap; job `timeout-minutes` set
- [ ] The pinned `@anthropic-ai/claude-code` version in the workflow exists on npm (it was copied from the local 2.1.299 build)
- [ ] Auth is `CLAUDE_CODE_OAUTH_TOKEN` only; the workflow sets no `ANTHROPIC_API_KEY` and no `SHOWME_BARE`
- [ ] A calendar reminder (or README note) to renew the token before it expires after one year
- [ ] One manual `workflow_dispatch` run is green and the Pages URL loads

### T-2: CI check on every push
Status: Ready
Owns: .github/workflows/check.yml (new); README.md badge line
Blocked by: none
Paid run: no
Why: The Stop hook guards local sessions; CI should guard pushes and PRs the same way.
Done when:
- [ ] Workflow runs `pip install -r requirements.txt` then `python scripts/check.py` on push and pull_request, Python 3.12
- [ ] No secrets are used by this workflow
- [ ] README has a status badge for it

### T-3: Agendas must never read as decisions
Status: Ready
Owns: pipeline/verify.py `code_checks()` (new `agenda_tense` check); tests/test_verify.py new class; tests/fixtures/kansascity/ agenda text (via scripts/refresh_fixture.py --agenda)
Blocked by: none
Paid run: no
Why: An agenda says what's planned. A claim like "passed" on an agenda is wrong even if the quote exists.
Done when:
- [ ] For `kind == "agenda"`, a claim with outcome passed/adopted/failed, or "passed"/"approved" in the statement, is rejected with reason `agenda_states_outcome`
- [ ] The KC agenda PDF text for event 19561 is in the fixture, so the offline nightly test no longer logs an ingest error for it
- [ ] Tests cover both a rejected and an allowed ("is scheduled for a vote") agenda claim

### T-4: Add Columbia as a second Legistar source
Status: Ready
Owns: pipeline/sources/__init__.py `get_source`; `COMO_BODIES` constant in pipeline/sources/legistar.py; tests/fixtures/gocolumbiamo/ (new); tests/test_columbia.py (new)
Blocked by: none
Paid run: no (the fixture is free to download)
Why: Proves the adapter isn't hard-wired to Kansas City. Same API, client `gocolumbiamo`.
Done when:
- [ ] `get_source("columbia")` returns a LegistarSource with prefix `como` and City Council bodies
- [ ] A real cached Columbia meeting fixture (made with refresh_fixture.py, given a `--client` flag) passes the same list/fetch tests as KC
- [ ] The site footer credit names the source city per document, not always Kansas City

### T-5: Measure the fact-checker's catch rate with planted errors
Status: Ready
Owns: pipeline/canary.py (new); one call in pipeline/run.py `process()` after the fact-checker stage; tests/test_canary.py (new)
Blocked by: none
Paid run: yes (adds ~10% to the fact-checker stage)
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
Paid run: no
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
Paid run: no
Why: Per-member votes come straight from the API: exact, free, and no model involved.
Done when:
- [ ] For each accepted vote claim with a matter number, the page shows who voted Aye/Nay/Excused, taken from api_items, not from agent output
- [ ] Labelled "From the city's vote record" so readers can tell it from AI text
- [ ] Offline test checks the 260919 roll call renders with 12 Ayes and Robinson excused

## In progress

## Review

## Done
- T-0: Scaffold: KC Legistar ingester with offline fixture, three pipeline agents, code checks, site builder, check script + Stop hook (2026-10-29)
