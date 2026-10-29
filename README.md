# showme-council

Plain-language, fact-checked summaries of Kansas City Council records, built
nightly by a team of Claude agents.

Each night it pulls new agendas and minutes from the city's Legistar API. An
**extractor** agent pulls out votes, spending and dates, each with a verbatim quote.
A **summarizer** writes a short summary from those facts alone. A **fact-checker**
agent checks every fact against the source text, and code checks quotes, numbers and
the city's own vote record. Only what passes both is published, and every page
shows how much was rejected.

- How it works, how claims are scored, schedule options and cost: [DESIGN.md](DESIGN.md)
- Rules for agents and people working in the repo: [CLAUDE.md](CLAUDE.md)
- Backlog for parallel builder sessions: [TASKS.md](TASKS.md)

## Run it

```
pip install -r requirements.txt
python scripts/check.py                                   # offline tests, free

# offline end-to-end with stub agents (free)
python -m pipeline.run nightly --fixture --stub tests/fixtures/kansascity/stub --days 10

# one real document (uses plan usage: check the estimate first)
python -m pipeline.run ingest --since 2026-10-22 --until 2026-10-23 --limit 1
python -m pipeline.run estimate kc-19561-minutes
python -m pipeline.run process kc-19561-minutes --max-usd 1.50
python -m pipeline.run build-site                         # -> site/index.html
```

Real runs use a Claude subscription (Pro/Max): log the CLI in with `claude auth login`,
or set `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (this is what CI uses). They
draw on plan usage, not an API bill. Set `CLAUDE_BIN` if `claude` isn't on PATH.
(An API-key fork can set `ANTHROPIC_API_KEY` and `SHOWME_BARE=1` instead.)

Unofficial and AI-written. Always check the linked official record. Source records:
City of Kansas City, Missouri, via Legistar.
