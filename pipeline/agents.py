"""Runs one pipeline agent as a headless Claude Code call, or returns canned output (--stub).

The agent's instructions live in .claude/agents/<name>.md (one source of truth for
people and for the pipeline). Each call is:

    claude -p <task> --agents <json built from the .md files> --agent <name>
           --output-format json --json-schema schemas/<schema>.json
           --tools "" --max-budget-usd <cap> --no-session-persistence ...

with the document payload on stdin. No tools: the agents only read what they're given
and return JSON, so a prompt injection in a PDF has nothing to act with.

Auth (DESIGN.md "Auth decision"): the Claude subscription. Locally that's the
`claude auth login` session; in CI it's CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`
(valid one year). An API-key fork can set ANTHROPIC_API_KEY and SHOWME_BARE=1 instead;
--bare never reads OAuth, so it is API-key only.
"""

import json
import os
import re
import subprocess
import time

from pipeline import paths

TASK = ("Process the JSON input on stdin exactly as your instructions describe and "
        "return only the structured output.")


def load_agent(name):
    with open(os.path.join(paths.AGENTS_DIR, f"{name}.md"), encoding="utf-8") as f:
        text = f.read()
    text = text.replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{name}.md has no frontmatter")
    front = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            front[k.strip()] = v.strip()
    return {"description": front.get("description", ""), "prompt": m.group(2).strip(),
            "model": front.get("model") or None}


def load_schema(schema):
    with open(os.path.join(paths.SCHEMAS_DIR, f"{schema}.json"), encoding="utf-8") as f:
        return json.load(f)


def build_command(name, schema, agents_file, max_usd):
    exe = os.environ.get("CLAUDE_BIN", "claude")
    cmd = [exe, "-p", TASK,
           "--agents", agents_file, "--agent", name,
           "--output-format", "json",
           "--json-schema", json.dumps(load_schema(schema), separators=(",", ":")),
           "--tools", "",
           "--max-budget-usd", f"{max_usd:.2f}",
           "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
           "--effort", os.environ.get("SHOWME_EFFORT", "medium")]
    if os.environ.get("SHOWME_BARE") == "1":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("SHOWME_BARE=1 needs ANTHROPIC_API_KEY: bare mode ignores subscription logins")
        cmd.insert(1, "--bare")
    return cmd


def clean_env():
    """Environment for the child `claude`. When this runs inside a Claude Code session (desktop
    app, or a terminal `claude`), that session's own variables would make the child think it
    is a nested session or route it through the parent's proxy. Drop them; keep real auth."""
    env = dict(os.environ)
    inside_host = "CLAUDE_CODE_HOST_SESSION_ID" in env or "CLAUDECODE" in env
    for k in list(env):
        if k in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
            continue
        if k.startswith(("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_")) or k in ("CLAUDECODE", "CLAUDE_PID"):
            del env[k]
    if inside_host:
        env.pop("ANTHROPIC_BASE_URL", None)
    if env.get("SHOWME_BARE") != "1":
        # Subscription mode: an API key or bearer token outranks the subscription login and
        # would silently move the run to API billing. Only SHOWME_BARE=1 opts into that.
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
    return env


def _structured(resp):
    if isinstance(resp.get("structured_output"), dict):
        return resp["structured_output"]
    # Fallback: some CLI versions put the JSON in `result` as text.
    txt = resp.get("result") or ""
    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        return json.loads(m.group(0))
    raise RuntimeError(f"no structured output; result was: {txt[:300]!r}")


def run_agent(name, schema, payload, out_dir, max_usd, stub_dir=None, timeout=900):
    """Return (output_dict, usage_dict). Also writes <out_dir>/<name>.response.json."""
    os.makedirs(out_dir, exist_ok=True)
    if stub_dir:
        with open(os.path.join(stub_dir, f"{name}.json"), encoding="utf-8") as f:
            return json.load(f), {"stub": True, "cost_usd": 0.0}

    agent = load_agent(name)
    agents_file = os.path.join(out_dir, "_agents.json")
    with open(agents_file, "w", encoding="utf-8") as f:
        json.dump({name: agent}, f)

    env = clean_env()
    env["SHOWME_PIPELINE"] = "1"  # tells the Stop hook to stay out of pipeline runs
    t0 = time.time()
    proc = subprocess.run(build_command(name, schema, agents_file, max_usd),
                          input=json.dumps(payload, ensure_ascii=False), capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout, env=env, cwd=paths.ROOT)
    with open(os.path.join(out_dir, f"{name}.response.json"), "w", encoding="utf-8") as f:
        f.write(proc.stdout)
    try:
        resp = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"{name}: claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[:500]}")
    if resp.get("is_error"):
        raise RuntimeError(f"{name}: {resp.get('subtype')}: {str(resp.get('result'))[:500]}")
    usage = {
        "cost_usd": resp.get("total_cost_usd"),
        "duration_s": round(time.time() - t0, 1),
        "num_turns": resp.get("num_turns"),
        "usage": resp.get("usage"),
        "model_usage": resp.get("modelUsage"),
    }
    return _structured(resp), usage
