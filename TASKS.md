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
Status: In progress. Step 1 done 2026-10-29 (repo created, token saved, one manual run green). Remaining steps need the user's OK and
an answer on repo visibility (GitHub Free needs a public repo for Pages).
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
- [x] `concurrency` set so two nights never overlap; job `timeout-minutes` set (step 1)
- [x] The pinned `@anthropic-ai/claude-code` version in the workflow exists on npm (2.1.312, verified, and installed on the runner)
- [x] Auth is `CLAUDE_CODE_OAUTH_TOKEN` only (`${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`); the workflow sets no `ANTHROPIC_API_KEY` and no `SHOWME_BARE` (pinned by tests/test_workflow_safety.py)
- [x] The user added the secret themselves; the session saw only its name in `gh secret list`
- [ ] A calendar reminder (or README note) to renew the token before it expires after one year
- [x] One manual `workflow_dispatch` run is green (run 40953248835, Oct 22 minutes: 60 facts, 53 passed, 25 of 29 votes, 72.3k tokens in / 12.1k out, 6 turns, 62 s)
- [ ] The Pages URL loads

Step-1 safety, pinned by tests: manual trigger only (no pull_request, push or comment triggers), `permissions: contents: read`, every action pinned to a
commit SHA, the token on a single step, inputs passed as validated env vars. The schedule, commit-back and Pages each widen what the workflow can do
(`contents: write`, `pages: write`, `id-token: write`) and need the user's OK first.

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
Status: Ready (do first: Sonnet's checker has flagged 0 of 118 claims and nothing yet shows it would catch an error)
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

### T-10: Give the headline its own claim list
Status: Ready
Owns: schemas/summarizer.json; .claude/agents/summarizer.md; pipeline/verify.py `decide()` headline rule; pipeline/run.py (the headline entry sent to the fact-checker); tests/test_verify_fixes.py HeadlineTests
Blocked by: none
Uses plan usage: yes (one real run to see the summarizer return the field; give the heads-up first)
Why: The headline now falls back to a plain title if any claim the summary cited was rejected, which on a long meeting is nearly always. The summarizer should say which claims the headline relies on.
Done when:
- [ ] The summarizer returns `headline_claim_ids`; the headline is published only if the checker marks it FAITHFUL against those claims and all of them were accepted
- [ ] Offline test: a rejected claim that the headline does not cite no longer costs the headline; one it does cite still does
- [ ] A saved run with no `headline_claim_ids` keeps the conservative rule

### T-11: Match the city's own wording for outcomes (held, referred, advanced...)
Status: Ready
Owns: pipeline/verify.py `_OUTCOME_WORDS` and `api_check()`; tests/test_verify.py ApiTests; a re-score of tests/fixtures/kansascity/runs/ (not the frozen test)
Blocked by: none
Uses plan usage: no
Why: Test 2 (docs/MODEL-COMPARISON.md): the committee minutes record "Hold on Agenda"; the check looks for the word "held" and reported `api_disagrees` on two true facts. Document 3 failed the 80% bar on it. The city's action vocabulary seen so far: Adopted, Adopted as Substituted, Adv and Do Pass, Adv and Do Pass as Cmte Sub, Held on Docket, Hold on Agenda, Move To Introduce, Passed, Passed as Substituted, Re-referred, received and filed, referred.
Done when:
- [ ] "held" matches "Held on Docket", "Hold on Agenda" and "Held in Committee"; "referred" matches "Re-referred"; "Adv and Do Pass" is checkable (an `advanced` outcome), instead of `other` being unchecked
- [ ] A claim that disagrees with the city's wording still gets `api_disagrees` (tests for each pair, including a wrong one)
- [ ] The saved outputs of all three test-2 documents are re-scored with the new code and reported as a labelled post-hoc re-score, never as a pass of the pre-registered test

### T-12: Verify derived tallies against the API roll call
Status: Ready
Owns: pipeline/verify.py (new `tally_check()` beside `numbers_check`); pipeline/run.py `process()` wiring; tests/test_verify.py
Blocked by: none
Uses plan usage: no
Why: "Resolution 260897 passed with all 13 members voting aye" is true (the city's roll call has 13 Ayes) but was rejected because 13 isn't in the quote: it is the model's count of the names. The roll call is already in `api_items`.
Done when:
- [ ] A number in a statement that equals the Aye / Nay / Excused count of that matter's API roll call is accepted without being in the quote
- [ ] A wrong tally (say 12 when the roll call has 13) is still rejected
- [ ] No other number is exempted

### T-13: Place items whose minutes wording differs from the API title
Status: Ready
Owns: pipeline/verify.py `matter_blocks()`; tests/test_matter_blocks_and_escalation.py
Blocked by: none
Uses plan usage: no
Why: A committee substitute prints new wording in the minutes ("identify up to $15,000,000.00") while the API keeps the original title ("estimate costs necessary..."), so Resolution 260885 can't be located and its number must then appear in the quote. Two true facts were rejected for it in document 1.
Done when:
- [ ] An item that the title probe can't place is located another way (e.g. the legislation number itself appearing in the item's trailing lines), with no loosening for items that are placed
- [ ] The two 260885 facts from the saved run pass; a wrong-item quote is still rejected

## In progress

## Review

## Done
- T-0: Scaffold: KC Legistar ingester with offline fixture, three pipeline agents, code checks, site builder, check script + Stop hook (2026-10-29)
- T-8: Coverage metric from the city's own vote record, plus a "this may need Opus: only N of M voted items covered" stop (floor 40%, 5+ votes); tests pin Opus 19/29, Sonnet first prompt 4/29, Sonnet coverage prompt 26/29 (2026-10-29)
- T-9: Extractor prompt asks for one fact per voted or money item. One Sonnet 5.5 run on kc-19561-minutes: 60 facts, 55 pass, coverage 26/29, all 42 vote facts match the city's record. Found and fixed a first-occurrence flaw in the matter-block check on the way (docs/MODEL-COMPARISON.md) (2026-10-29)
