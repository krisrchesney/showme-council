"""Runs one pipeline agent as a headless Claude Code call, or returns canned output (--stub).

The agent's instructions live in .claude/agents/<name>.md (one source of truth for
people and for the pipeline). Each call is:

    claude -p <task> --agents <json built from the .md files> --agent <name>
           --output-format json --json-schema schemas/<schema>.json
           --tools "" --max-budget-usd <loop cap> --no-session-persistence ...

with the document payload on stdin. No tools: the agents only read what they're given
and return JSON, so a prompt injection in a PDF has nothing to act with.

Auth (DESIGN.md "Auth decision"): the Claude subscription. Locally that's the
`claude auth login` session; in CI it's CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`
(valid one year). An API-key fork can set ANTHROPIC_API_KEY and SHOWME_BARE=1 instead;
--bare never reads OAuth, so it is API-key only.
"""

import glob
import json
import os
import re
import shutil
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


EXE = "claude.exe" if os.name == "nt" else "claude"


def _version_key(path):
    """Sort key for .../claude-code/<version>/<hash>/claude.exe: numeric, so 2.1.10 > 2.1.9."""
    m = re.search(r"claude-code[\\/]+(\d+(?:\.\d+)*)[\\/]", path)
    return (tuple(int(x) for x in m.group(1).split(".")) if m else (), os.path.getmtime(path))


def _newest(pattern):
    hits = glob.glob(pattern)
    return max(hits, key=_version_key) if hits else None


def find_claude(env=None, which=shutil.which, home=None):
    """Locate the claude CLI. Returns (path, how_it_was_found); raises FileNotFoundError listing
    everywhere it looked. Order:
      1. CLAUDE_BIN (explicit; if set but missing that is an error, not a fallthrough)
      2. `claude` on PATH
      3. the standalone install, ~/.local/bin/claude(.exe)
      4. the newest version folder of the copy bundled with the Claude desktop app.
         The desktop app is a packaged Windows app: its real files live under
         %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude\\claude-code\\<version>\\<hash>\\,
         and %APPDATA%\\Claude\\claude-code only resolves inside the app's own sessions,
         so both are searched, packaged location first.
    """
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    tried = []

    explicit = env.get("CLAUDE_BIN")
    if explicit:
        if os.path.isfile(explicit):
            return explicit, "CLAUDE_BIN"
        raise FileNotFoundError(f"CLAUDE_BIN is set to {explicit!r} but no file is there")

    on_path = which("claude")
    tried.append("`claude` on PATH")
    if on_path:
        return on_path, "PATH"

    standalone = os.path.join(home, ".local", "bin", EXE)
    tried.append(standalone)
    if os.path.isfile(standalone):
        return standalone, "standalone install"

    roots = []
    if env.get("LOCALAPPDATA"):
        roots.append(os.path.join(env["LOCALAPPDATA"], "Packages", "Claude_*", "LocalCache", "Roaming"))
    if env.get("APPDATA"):
        roots.append(env["APPDATA"])
    for root in roots:
        pattern = os.path.join(root, "Claude", "claude-code", "*", "*", EXE)
        tried.append(pattern)
        hit = _newest(pattern)
        if hit:
            return hit, "desktop app's bundled copy (newest version)"
    raise FileNotFoundError("claude CLI not found. Looked in: " + "; ".join(tried) +
                            ". Install it with: irm https://claude.ai/install.ps1 | iex   (or set CLAUDE_BIN)")


def login_instructions(path=None):
    """Exact commands to log in, using the full resolved path so the user can paste them."""
    path = path or find_claude()[0]
    return f'& "{path}" auth login'


def build_command(name, schema, agents_file, loop_cap):
    try:
        exe = find_claude()[0]
    except FileNotFoundError:
        exe = "claude"          # run_agent re-resolves strictly and gives the helpful error
    cmd = [exe, "-p", TASK,
           "--agents", agents_file, "--agent", name,
           "--output-format", "json",
           "--json-schema", json.dumps(load_schema(schema), separators=(",", ":")),
           "--tools", "",
           "--max-budget-usd", f"{loop_cap:.2f}",   # runaway-loop tripwire, API-equivalent units
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


class AgentOutputError(RuntimeError):
    """The agent ran but returned nothing that parses against its schema."""


def _structured(resp):
    if isinstance(resp.get("structured_output"), dict):
        return resp["structured_output"]
    # Fallback: some CLI versions put the JSON in `result` as text.
    txt = resp.get("result") or ""
    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise AgentOutputError(f"unparseable JSON in result: {e}") from e
    raise AgentOutputError(f"no structured output; result was: {txt[:200]!r}")


def run_agent(name, schema, payload, out_dir, loop_cap, stub_dir=None, timeout=900, model=None):
    """Return (output_dict, usage_dict). Also writes <out_dir>/<name>.response.json.
    `model` overrides the agent frontmatter model (the user's explicit escalation)."""
    os.makedirs(out_dir, exist_ok=True)
    if stub_dir:
        with open(os.path.join(stub_dir, f"{name}.json"), encoding="utf-8") as f:
            return json.load(f), {"stub": True, "tokens_in": 0, "tokens_out": 0, "num_turns": 0,
                                  "duration_s": 0.0, "api_equiv_usd": 0.0, "models": []}

    agent = load_agent(name)
    if model:
        agent["model"] = model
    agents_file = os.path.join(out_dir, "_agents.json")
    with open(agents_file, "w", encoding="utf-8") as f:
        json.dump({name: agent}, f)

    find_claude()   # fail with the list of places searched, not a bare "file not found"
    env = clean_env()
    env["SHOWME_PIPELINE"] = "1"  # tells the Stop hook to stay out of pipeline runs
    t0 = time.time()
    proc = subprocess.run(build_command(name, schema, agents_file, loop_cap),
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
    u = resp.get("usage") or {}
    usage = {
        "tokens_in": (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
                     + (u.get("cache_read_input_tokens") or 0),
        "tokens_out": u.get("output_tokens") or 0,
        # Claude Code's estimate of what these tokens would cost at API rates. For comparing
        # models and runs only; on the subscription nothing is billed per token.
        "api_equiv_usd": resp.get("total_cost_usd") or 0.0,
        "duration_s": round(time.time() - t0, 1),
        "num_turns": resp.get("num_turns"),
        "usage": resp.get("usage"),
        "model_usage": resp.get("modelUsage"),
        "models": sorted((resp.get("modelUsage") or {}).keys()),
    }
    return _structured(resp), usage
