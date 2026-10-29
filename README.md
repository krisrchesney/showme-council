# showme-council

Plain-language, fact-checked summaries of Kansas City Council records, built
nightly by a team of Claude agents.

Each night it pulls new agendas and minutes from the city's Legistar API. An
**extractor** agent pulls out votes, spending and dates, each with a verbatim quote.
A **summarizer** writes a short summary from those facts alone. A **fact-checker**
agent checks every fact against the source text, and code checks quotes, numbers and
the city's own vote record. Only what passes both is published, and every page
shows how much was rejected.

- How it works, how claims are scored, schedule options and plan usage: [DESIGN.md](DESIGN.md)
- Rules for agents and people working in the repo: [CLAUDE.md](CLAUDE.md)
- Backlog for parallel builder sessions: [TASKS.md](TASKS.md)

## Run it

```
pip install -r requirements.txt
python scripts/check.py                                   # offline tests, free

# offline end-to-end with stub agents (free)
python -m pipeline.run nightly --fixture --stub tests/fixtures/kansascity/stub --days 10

# one real document (uses plan usage; `estimate` shows the expected tokens)
python -m pipeline.run ingest --since 2026-10-22 --until 2026-10-23 --limit 1
python -m pipeline.run estimate kc-19561-minutes
python -m pipeline.run process kc-19561-minutes
python -m pipeline.run build-site                         # -> site/index.html
```

Real runs use a Claude subscription (Pro/Max) and draw on plan usage, not an API bill.
Install the standalone CLI once (`irm https://claude.ai/install.ps1 | iex` on Windows), then ask the
repo which CLI it will use and for the exact login command with its full path:

```
python -m pipeline.run claude-path
```

It looks at `CLAUDE_BIN`, then `claude` on PATH, then `~/.local/bin/claude.exe`, then the newest
version of the copy bundled with the desktop app. That app is a packaged Windows app, so its real
files are under `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code\`; the
`%APPDATA%` path only works inside the app's own sessions. In CI the login is the
`CLAUDE_CODE_OAUTH_TOKEN` secret from `claude setup-token` (see DESIGN.md).
(An API-key fork can set `ANTHROPIC_API_KEY` and `SHOWME_BARE=1` instead.)

Unofficial and AI-written. Always check the linked official record. Source records:
City of Kansas City, Missouri, via Legistar.
