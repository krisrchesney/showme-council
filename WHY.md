# Why this exists

*Written November 2026. Unofficial and AI-written. Always check the linked official record. Source records: City of Kansas City, Missouri, via its public records feed.*

## In 30 seconds

City council agendas and minutes are long, dense documents that few residents read. Every night this project pulls the new ones and has a team of three AI agents turn them into short plain-language summaries. One agent pulls out the facts, one writes the summary from those facts alone, and one checks every fact against the original. Only what passes the checks is published, and each page shows how much was rejected.

## Why I built it

I wanted to see whether a team of AI agents could produce something I'd trust without reading the source myself. Local government records are public, free to use and made of facts that can be checked, such as who voted how on which item, so a wrong summary is easy to catch.

## How it works

1. **Collect** the day's new records from the city's public feed.
2. **Extract** the votes, spending and dates, each with an exact quote from the document.
3. **Check with code.** Is the quote really in the document, do the numbers match it, and does the city's own vote record agree?
4. **Summarize** using only the checked facts. This agent never sees the original document, so it can't add anything new.
5. **Fact-check with a second agent** that sees the document and assumes the others made mistakes.
6. **Publish** only what passed both the code and the fact-checker.

## Choices I made, and why

- **Every fact carries its quote, page and a link to the official record**, so a reader can verify it.
- **Three agents with separate jobs**, because the writer can't invent a fact it was never given, and the checker has no reason to trust the others.
- **Code checks alongside the AI checker**, so the checks don't all rest on another AI.
- **The agents can't do anything except read and answer.** If a document contains a hidden instruction, there's nothing for it to act on.
- **Show the rejection count on every page**, so readers can see how much was thrown out.
- **A mid-size AI model, not the largest.** Better instructions closed the gap and cost less.

## What I found

On one test document, a 28-page set of minutes with 29 votes:
- **The final setup extracted 60 facts, and 55 (92%) passed every check.**
- **It covered 26 of the 29 votes (90%).** A first, stricter set of instructions covered only 4.
- **None of the accepted facts were contradicted by the city's own vote record.**

[Details and the model comparison.](docs/MODEL-COMPARISON.md)

**What not to trust:** that's one document and one run each, a first look and not a benchmark. The summaries are AI-written and can still be wrong, so the linked official record is the source of truth.

## What's not finished

- The nightly run covers meeting minutes only. Comparing what an agenda planned with what actually happened is designed but not added.
- Only Kansas City is covered.

## Where to look

[Live site](https://krisrchesney.github.io/showme-council/) · [README](README.md) · [Design](DESIGN.md) · [Model comparison](docs/MODEL-COMPARISON.md)
