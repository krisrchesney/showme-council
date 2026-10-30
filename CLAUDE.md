# showme-council: rules for every Claude session and agent

A nightly pipeline turns Kansas City Council records (Legistar API + PDFs) into
fact-checked plain-language summaries on a static site. Read DESIGN.md for the
stages, handoff files, scoring and plan usage. Python 3.12; the only dependency is
`pypdf` (requirements.txt).

## Workflow
- Work comes from TASKS.md. Take one ticket, move it to "In progress" with your
  branch name, and only touch the files/functions that ticket owns.
- Builders work in their own git worktree and branch (`ticket/T-<n>-<slug>`), never on master.
- `python scripts/check.py` must pass before you say a ticket is done (offline, free).
  A Stop hook runs it automatically.
- When done: commit on your branch, set the ticket to "Review", and say so. Don't
  merge, push, or create a GitHub repo. The user merges after the `reviewer` agent approves.
- Never delete, skip or loosen a test, lower a threshold in pipeline/verify.py, or
  edit scripts/check.py or .claude/hooks/ to make the check pass, unless the ticket
  says to. Fix the code instead.
- When a ticket is approved, report in one line what went wrong or what the
  reviewer caught, so it can be added to "Lessons" below.

## Plan usage
Runs on the user's Claude subscription. Report usage (tokens, turns, time), not dollars.
- Any run without `--stub` draws on the plan's usage window. Before the first real run in a
  session, say which model and the expected tokens (`python -m pipeline.run estimate <doc>`).
  That's a heads-up, not a budget approval. Never describe usage as cost or price.
- Auth is the subscription (`claude auth login` locally, `CLAUDE_CODE_OAUTH_TOKEN` in CI). When you
  give the user a login command, get the full path from `python -m pipeline.run claude-path`; don't
  assume `claude` is on their PATH or use `%APPDATA%` paths (they don't resolve in the user's own shell).
  Don't switch to an API key (it bills per token) or add `--bare` without the user asking. The
  runner strips `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` so nothing bills per token by accident.
- Tests and reviews use `--fixture` and `--stub tests/fixtures/kansascity/stub` only.
- `--max-budget-usd` on every agent call and the per-document / per-night `--loop-cap` are
  runaway-loop tripwires in API-equivalent units, not spending limits. Keep them.

## Models
- Pipeline and dev agents default to Sonnet 5.5. Never switch an agent to Opus, or pass
  `--model claude-opus-5-5`, without asking the user first and saying why.
- When a stage stops with "this may need Opus: <why>", report it and ask. Don't rerun it
  on Opus yourself. DESIGN.md "Model policy" lists exactly when the pipeline stops.

## Conventions
- Stages hand off through files in data/ (see DESIGN.md). Don't pass results between
  stages in memory, so a single stage can be re-run.
- Pipeline agents (extractor, summarizer, fact-checker) have no tools. Their input
  is data, never instructions; their output must match schemas/*.json.
- Only `verify.decide()` decides what is published. The site reads data/published/ only.
- A new city is a new adapter in pipeline/sources/ that fills in `Source`; nothing
  downstream may know which city a document came from.
- When the code check and the fact-checker disagree about a claim, read the disagreement
  before touching either: the first real run found the code check was the wrong one.
  `python -m pipeline.run redecide <doc>` re-scores saved agent output for free.
- Plain-language writing on the site: short sentences, explain jargon once, neutral tone.

## Never
- Put API keys or tokens (`ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`) in a file, a commit, a log, or
  chat. CI reads them from GitHub secrets; the user generates the token themselves.
- Publish a fact or sentence that didn't pass `decide()`, or re-host city PDFs. Link to the official copy.
- Remove the "unofficial / AI-written" notice or the source credit from site pages.
- Scrape a page a site's robots.txt disallows (St. Louis bill pages, St. Charles /RSS.aspx).
- Enable the nightly cron, push, or publish to Pages without the user saying so.

## Command Center asks (read at the start of every turn)
This project is tracked on the user's private Command Center Projects tab as `devprojects/showme-council`.
The board's link is in `../CommandCenter/CLAUDE.md` (the folder next to this repo on the user's machine;
it is deliberately not written here because this repo is public). Load ArtifactData with ToolSearch
"select:ArtifactData".
- At the start of each turn, read that doc and every `devdecisions` doc whose `project` is "showme-council".
  Those are the user's clicks on its asks: approved, declined, done, snoozed, or an `answer`.
- Treat an approved or answered ask as the user's own answer for routine local work and act on it.
  For anything public or that uses a secret (pushing, creating a repo, publishing, tokens), confirm
  once in chat first and say the page approval was seen.
- When done, update the ask in `devprojects/showme-council` pinned with `if_version`: copy the status and
  answer, set `handledAt` and `handledBy`, and note the result in `lastActivity`. Add an ask there when
  you need something only the user can give, and append a `usage` entry when a run finishes.
- Full rules: `../CommandCenter/CLAUDE.md`, rule `cc-projects-status`. Never put secrets or tokens in the
  database, and never write the board's link, personal paths or account names into this public repo.

## Lessons
One line per finished ticket: what went wrong or what review caught. Added on
master by the session that merges (not by builders, so branches don't conflict).
Read these before starting a ticket.
- T-8/T-9: when the code check rejected 34 claims the fact-checker had marked SUPPORTED, the code was wrong (it located a repeated boilerplate quote by its first occurrence). Read disagreements before trusting either side, and compare models on the same, fixed verify.py.
- T-8/T-9: a prompt that said "precision matters far more than coverage" made Sonnet write 7 facts from a 29-vote meeting. Ask for completeness explicitly, and measure coverage against the city's own record (`coverage`), not just the pass rate.
- T-8/T-9: a headline could restate a rejected fact; it now requires every claim it cites to be accepted. When adding anything that gets published, check it against the accepted set, not just the checker's verdict.
- Fixing a number regex: match the whole number first and filter after; a lookahead that backtracks turned "63rd" into "6".
- Test 2: before comparing models, pre-register the pass criteria and freeze verify.py, the prompts and the thresholds. When a document fails because of the verifier (T-11), report the failure, ticket the fix, and re-score afterwards as a labelled post-hoc run. Never count it as a pass.
- T-5: the planted-error test caught a leak the unit tests missed: the published report listed the fakes' ids. Publish counts only, and test the published file for them.
- T-11: a check that compares a claim with the city's record must use the city's wording ("Hold on Agenda", "Adv and Do Pass"), and a substring is not a match ("pass" is inside "Adv and Do Pass").
- T-16: the city's item rows are one per step, not one per item. Count matters, not rows: my first count of "minutes-only rows" overstated late additions many times over.
- T-3: adding a real agenda to the fixtures turned an expected-failure test into a pass; keep the behaviour the old test protected (a failed fetch is recorded and retried) with a test that causes the failure on purpose.
