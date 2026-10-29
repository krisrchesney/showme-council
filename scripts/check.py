"""One command that answers "is the repo healthy?" - used by people, agents and the Stop hook.

    python scripts/check.py

Compiles every Python file, then runs the tests in tests/. Offline and free: no
network, no model calls. Exits non-zero on any failure.
"""

import os
import py_compile
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    failed = False
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".venv", "__pycache__", ".claude", "data", "site")]
        for name in filenames:
            if name.endswith(".py"):
                try:
                    py_compile.compile(os.path.join(dirpath, name), doraise=True)
                except py_compile.PyCompileError as e:
                    print(f"SYNTAX ERROR: {e.msg}")
                    failed = True

    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"], cwd=ROOT
    )
    failed = failed or tests.returncode != 0

    print("check: FAILED" if failed else "check: OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
