"""Scan a built site folder for anything that must never be published. Exit 1 on a hit; prints file and rule, never the text.

    python scripts/scan_site.py SITE_DIR

The explorer is built from public records and published checks, so none of these should ever appear. The scan is the last step
before a page artifact is uploaded: a token, a local Windows or home path, a private artifact link, a key header, an email
address that is not the public noreply one.
"""

import os
import re
import sys

RULES = [
    ("oauth token name", re.compile(r"CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN")),
    ("api key shape", re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gho_[A-Za-z0-9]{20,}")),
    ("authorization header", re.compile(r"(?i)authorization:\s*(basic|bearer)\s+\S+")),
    ("windows user path", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+\w+", re.I)),
    ("unix home path", re.compile(r"/(home|Users)/[a-z][\w.-]+/(?!showme)", re.I)),
    ("private artifact link", re.compile(r"claude\.ai/(artifact|code|chat)/", re.I)),
    ("email address", re.compile(r"[\w.+-]+@(?!users\.noreply\.github\.com)[\w-]+\.[a-z]{2,}", re.I)),
]
TEXT = (".html", ".css", ".js", ".json", ".txt", ".xml", ".svg")


def scan(root):
    hits = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.endswith(TEXT):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            for label, rx in RULES:
                if rx.search(text):
                    hits.append((os.path.relpath(path, root).replace("\\", "/"), label))
    return hits


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1 or not os.path.isdir(argv[0]):
        print("usage: scan_site.py SITE_DIR")
        return 2
    hits = scan(argv[0])
    for path, label in hits:
        print(f"PRIVATE-LOOKING TEXT ({label}) in {path}")
    print(f"scan: {'FAILED, ' + str(len(hits)) + ' hit(s)' if hits else 'clean'}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
