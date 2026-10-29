"""Where every stage reads and writes. Each stage hands off through files, never memory."""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("SHOWME_DATA_DIR") or os.path.join(ROOT, "data")

RAW = os.path.join(DATA, "raw")              # ingester output: one folder per document
WORK = os.path.join(DATA, "work")            # agent handoff files: facts, summary, verdicts, report
PUBLISHED = os.path.join(DATA, "published")  # accepted claims + sentences only; the site is built from this
STATE = os.path.join(DATA, "state.json")     # which documents are already processed
METRICS = os.path.join(DATA, "metrics.jsonl")  # one line per processed document: pass/reject counts, tokens, time
SITE = os.environ.get("SHOWME_SITE_DIR") or os.path.join(ROOT, "site")

AGENTS_DIR = os.path.join(ROOT, ".claude", "agents")
SCHEMAS_DIR = os.path.join(ROOT, "schemas")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def raw_dir(doc_id):
    return os.path.join(RAW, doc_id)


def work_dir(doc_id):
    return os.path.join(WORK, doc_id)
