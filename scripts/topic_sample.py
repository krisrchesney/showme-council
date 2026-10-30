"""Measure how accurate the keyword topic rules are, against a model, on a sample of titles (T-19).

    python scripts/topic_sample.py --history history [--n 300] [--seed 7] [--out preview/topic-sample.json]        # plan only
    python scripts/topic_sample.py --history history --run                                                         # USES PLAN USAGE

Without --run it builds the sample, shows how it is spread across the rules' topics and prints the token estimate, and calls
no model. With --run it sends the sample to the topic-tagger agent in batches and reports how often the rules agree with it,
overall and per topic, plus the disagreements so a person can judge who is right. The model's tags are used only for this
measurement; they never appear on a page. The model is not ground truth: agreement is a measure, not a verdict.
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import paths  # noqa: E402
from pipeline.agents import add_breakdowns, run_agent  # noqa: E402
from pipeline.compare import load_history  # noqa: E402
from pipeline.topics import DESCRIPTIONS, TOPICS, topic_list, topic_of  # noqa: E402

BATCH = 50
TITLE_CHARS = 500
CHARS_PER_TOKEN = 3.5
OVERHEAD_TOKENS = 5500     # per call: Claude Code's own prompt plus the agent's instructions (measured: a first estimate of 1,500 was low by about 1.8x overall)


def distinct_council_matters(events, rows):
    council = {e["event_id"] for e in events if e["body"] == "Council"}
    seen = {}
    for r in sorted(rows, key=lambda r: (r["event_id"], r["agenda_seq"] or 0)):
        if r["event_id"] in council and r["matter_file"] and r["matter_file"] not in seen and r["title"]:
            seen[r["matter_file"]] = r["title"]
    return seen


def build_sample(matters, n, seed, exclude=()):
    """About n/len(TOPICS) titles per rule topic (all of a small topic), so every rule and the 'other' bucket are tested."""
    rng = random.Random(seed)
    groups = {t: [] for t in TOPICS}
    for mf, title in sorted(matters.items()):
        if mf not in exclude:
            groups[topic_of(title)].append((mf, title))
    per = max(1, n // len(TOPICS))
    sample = []
    for t in TOPICS:
        g = groups[t][:]
        rng.shuffle(g)
        sample.extend((mf, title, t) for mf, title in g[:per])
    leftovers = [(mf, title, topic_of(title)) for t in TOPICS for mf, title in groups[t] if (mf, title, t) not in sample]
    rng.shuffle(leftovers)
    sample.extend(leftovers[:max(0, n - len(sample))])
    return sample[:n]


def estimate_tokens(sample):
    calls = -(-len(sample) // BATCH)
    tin = sum(min(len(t), TITLE_CHARS) / CHARS_PER_TOKEN for _, t, _ in sample) + calls * (OVERHEAD_TOKENS + 400)
    tout = len(sample) * 12 + calls * 200
    return {"calls": calls, "tokens_in": int(tin), "tokens_out": int(tout)}


def compare_tags(sample, tags):
    """Agreement between the rules and a model's tags: overall, and per rule topic."""
    per, rows, main = {}, [], {}
    for i, (mf, title, rule) in enumerate(sample):
        model = tags.get(f"s{i}")
        listed = topic_list(title)
        ok = model in listed                      # the model's main topic is one of the rules' topics for the item
        p = per.setdefault(rule, {"n": 0, "agree": 0})
        p["n"] += 1
        p["agree"] += ok
        for t in listed:                          # for each topic the page would show: does the model call it the item's main topic?
            m = main.setdefault(t, {"n": 0, "model_main": 0})
            m["n"] += 1
            m["model_main"] += (model == t)
        rows.append({"id": f"s{i}", "matter_file": mf, "title": title, "rule": rule, "rules": listed, "model": model, "agree": ok,
                     "primary_agree": model == rule})
    n = len(rows)
    return {"n": n, "agree": sum(r["agree"] for r in rows), "rate": round(sum(r["agree"] for r in rows) / n, 3) if n else None,
            "primary_agree": sum(r["primary_agree"] for r in rows),
            "primary_rate": round(sum(r["primary_agree"] for r in rows) / n, 3) if n else None,
            "per_rule_topic": {t: dict(v, rate=round(v["agree"] / v["n"], 3)) for t, v in per.items()},
            "per_listed_topic": {t: dict(v, rate=round(v["model_main"] / v["n"], 3)) for t, v in main.items()}, "rows": rows}


def weighted_rate(per_rule_topic, population):
    """The agreement rate across ALL items, not just the sample. The sample is balanced across the rules' topics, so each topic's
    agreement is weighted by how common that topic is among all items. {topic: n_items} in, a rate out."""
    total = sum(population.values())
    got = sum(population.get(t, 0) * v["rate"] for t, v in per_rule_topic.items())
    seen = sum(population.get(t, 0) for t in per_rule_topic)
    return round(got / seen, 3) if seen else None


def run_sample(sample, out_dir, loop_cap=1.5, runner=run_agent):
    tags, usages = {}, []
    topics = [{"topic": t, "description": DESCRIPTIONS[t]} for t in TOPICS]
    for b in range(0, len(sample), BATCH):
        items = [{"id": f"s{b + j}", "title": title[:TITLE_CHARS]} for j, (_, title, _) in enumerate(sample[b:b + BATCH])]
        out, usage = runner("topic-tagger", "topic_tagger", {"topics": topics, "items": items}, out_dir, loop_cap)
        usages.append(usage)
        for t in out.get("tags", []):
            tags[t["id"]] = t["topic"]
    res = compare_tags(sample, tags)
    res["usage"] = {"tokens_in": sum(u.get("tokens_in", 0) for u in usages), "tokens_out": sum(u.get("tokens_out", 0) for u in usages),
                    "tokens": add_breakdowns(u.get("tokens") for u in usages),
                    "turns": sum(u.get("num_turns", 0) for u in usages), "seconds": round(sum(u.get("duration_s", 0.0) for u in usages), 1)}
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default="history")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=os.path.join("preview", "topic-sample.json"))
    ap.add_argument("--run", action="store_true", help="call the model (uses plan usage)")
    ap.add_argument("--exclude-from", default="", help="a topic-sample.json whose matters are left out, so the sample is fresh")
    a = ap.parse_args(argv)
    events, rows = load_history(a.history)
    matters = distinct_council_matters(events, rows)
    exclude = set()
    if a.exclude_from:
        with open(a.exclude_from, encoding="utf-8") as f:
            exclude = {r["matter_file"] for r in json.load(f)["rows"]}
    sample = build_sample(matters, a.n, a.seed, exclude)
    est = estimate_tokens(sample)
    spread = {t: sum(1 for _, _, r in sample if r == t) for t in TOPICS}
    print(f"{len(matters)} distinct Council matters; sample of {len(sample)}; by rule topic: {spread}")
    print(f"estimate if run: {est['calls']} calls, about {est['tokens_in']:,} tokens in and {est['tokens_out']:,} out")
    if not a.run:
        print("plan only: no model called (add --run)")
        return 0
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    res = run_sample(sample, os.path.join(os.path.dirname(a.out) or ".", "topic-sample-work"))
    population = {t: sum(1 for title in matters.values() if topic_of(title) == t) for t in TOPICS}
    res["sample_seed"] = a.seed
    res["fresh_of"] = a.exclude_from or None
    res["population"] = population
    res["weighted_rate"] = weighted_rate(res["per_rule_topic"], population)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    u = res["usage"]
    print(f"rules agree with the model on {res['agree']} of {res['n']} sampled ({round(100 * res['rate'])}%); across all items, weighted "
          f"by how common each topic is: {round(100 * res['weighted_rate'])}%; usage: {u['tokens_in']:,} in, "
          f"{u['tokens_out']:,} out, {u['turns']} turns, {u['seconds']:.0f} s -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
