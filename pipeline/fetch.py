"""Polite HTTP: one User-Agent, a delay between requests, a couple of retries. Standard library only."""

import json
import time
import urllib.error
import urllib.request

USER_AGENT = "showme-council/0.1 (civic records summarizer; https://github.com/krisrchesney)"
DELAY_SECONDS = 0.5
_last = [0.0]


def get_bytes(url, timeout=60, retries=2):
    for attempt in range(retries + 1):
        wait = DELAY_SECONDS - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries:
                raise RuntimeError(f"GET {url} failed: {e}") from e
            time.sleep(2 * (attempt + 1))


def get_json(url, **kw):
    return json.loads(get_bytes(url, **kw).decode("utf-8"))
