"""Commit a night's results to the `data` branch. Never touches master.

    python scripts/publish_data.py --data DIR [--remote URL_OR_PATH] [--branch data] [--dry-run]

Copies DIR/state.json, DIR/metrics.jsonl and DIR/published/ into a fresh checkout of the `data` branch
(created as an orphan branch the first time), commits if anything changed, and pushes. With --dry-run it does
everything except the push and prints what would be committed. The data branch holds only these files, so
code history on master stays clean and the site can always be rebuilt from it.

Run in CI by the job that has write access; the job that talks to the model never does.
To push to GitHub set PUBLISH_TOKEN (the workflow's own token); it is sent as a one-off header, not in the URL.
"""

import argparse
import base64
import os
import shutil
import subprocess
import sys
import tempfile

FILES = ("state.json", "metrics.jsonl")


_AUTH = []   # set per run by publish(); see _auth_args


def _auth_args(remote):
    """Credentials for pushing to GitHub, passed the way actions/checkout does: a one-off header on the git
    command line. Never in the remote URL, never written to a config file, and never in an error message."""
    token = os.environ.get("PUBLISH_TOKEN")
    if token and remote.startswith("https://github.com/"):
        b64 = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        return ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {b64}"]
    return []


def git(cwd, *args, check=True):
    r = subprocess.run(["git", *_AUTH, *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.stdout.strip()}")
    return r


def publish(data_dir, remote, branch="data", dry_run=False, message=None, identity=("showme-council bot", "bot@users.noreply.github.com")):
    """Returns (committed: bool, files_changed: list[str], pushed: bool)."""
    global _AUTH
    _AUTH = _auth_args(remote)
    work = tempfile.mkdtemp(prefix="showme-data-")
    try:
        exists = git(work, "ls-remote", "--exit-code", "--heads", remote, branch, check=False).returncode == 0
        if exists:
            git(work, "clone", "--quiet", "--branch", branch, "--single-branch", remote, "repo")
            repo = os.path.join(work, "repo")
        else:
            repo = os.path.join(work, "repo")
            os.makedirs(repo)
            git(repo, "init", "--quiet")
            git(repo, "checkout", "--quiet", "--orphan", branch)
            git(repo, "remote", "add", "origin", remote)
        git(repo, "config", "user.name", identity[0])
        git(repo, "config", "user.email", identity[1])

        for name in FILES:
            src = os.path.join(data_dir, name)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(repo, name))
        pub_src, pub_dst = os.path.join(data_dir, "published"), os.path.join(repo, "published")
        if os.path.isdir(pub_src):
            shutil.rmtree(pub_dst, ignore_errors=True)
            shutil.copytree(pub_src, pub_dst)

        git(repo, "add", "--all")
        changed = [ln[3:] for ln in git(repo, "status", "--porcelain").stdout.splitlines()]
        if not changed:
            return False, [], False
        if dry_run:
            return True, changed, False
        git(repo, "commit", "--quiet", "-m", message or "Nightly data: results of the latest run")
        git(repo, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
        return True, changed, True
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _AUTH = []


def restore(data_dir, remote, branch="data"):
    """Copy the data branch's files into data_dir, so tonight's run starts from everything published so far.

    Without this a fresh runner would know nothing: it would reprocess old documents and the site would show only
    tonight's. Returns True if the branch existed. Never writes anywhere but data_dir."""
    global _AUTH
    _AUTH = _auth_args(remote)
    work = tempfile.mkdtemp(prefix="showme-restore-")
    try:
        if git(work, "ls-remote", "--exit-code", "--heads", remote, branch, check=False).returncode != 0:
            return False
        git(work, "clone", "--quiet", "--depth", "1", "--branch", branch, "--single-branch", remote, "repo")
        repo = os.path.join(work, "repo")
        os.makedirs(data_dir, exist_ok=True)
        for name in FILES:
            if os.path.exists(os.path.join(repo, name)):
                shutil.copyfile(os.path.join(repo, name), os.path.join(data_dir, name))
        if os.path.isdir(os.path.join(repo, "published")):
            shutil.rmtree(os.path.join(data_dir, "published"), ignore_errors=True)
            shutil.copytree(os.path.join(repo, "published"), os.path.join(data_dir, "published"))
        return True
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _AUTH = []


def restore_branch(dest, remote, branch):
    """Copy a whole branch's files into dest (for append-only stores such as agenda snapshots). True if the branch exists."""
    global _AUTH
    _AUTH = _auth_args(remote)
    work = tempfile.mkdtemp(prefix="showme-rb-")
    try:
        if git(work, "ls-remote", "--exit-code", "--heads", remote, branch, check=False).returncode != 0:
            return False
        git(work, "clone", "--quiet", "--depth", "1", "--branch", branch, "--single-branch", remote, "repo")
        repo = os.path.join(work, "repo")
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in files:
                src = os.path.join(root, name)
                target = os.path.join(dest, os.path.relpath(src, repo))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(src, target)
        return True
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _AUTH = []


def commit_tree(src_dir, remote, branch, message, dry_run=False, identity=("showme-council bot", "bot@users.noreply.github.com")):
    """Add src_dir's files to a branch, APPEND-ONLY: a file that already exists there with different content is an error,
    and nothing already on the branch is ever deleted. Returns (committed, files_added, pushed)."""
    global _AUTH
    _AUTH = _auth_args(remote)
    work = tempfile.mkdtemp(prefix="showme-ct-")
    try:
        repo = os.path.join(work, "repo")
        if git(work, "ls-remote", "--exit-code", "--heads", remote, branch, check=False).returncode == 0:
            git(work, "clone", "--quiet", "--branch", branch, "--single-branch", remote, "repo")
        else:
            os.makedirs(repo)
            git(repo, "init", "--quiet")
            git(repo, "checkout", "--quiet", "--orphan", branch)
            git(repo, "remote", "add", "origin", remote)
        git(repo, "config", "user.name", identity[0])
        git(repo, "config", "user.email", identity[1])
        for root, dirs, files in os.walk(src_dir):
            for name in files:
                src = os.path.join(root, name)
                target = os.path.join(repo, os.path.relpath(src, src_dir))
                if os.path.exists(target):
                    with open(src, "rb") as a, open(target, "rb") as b:
                        if a.read() != b.read():
                            raise FileExistsError(f"{os.path.relpath(src, src_dir)} already exists on {branch} with different content")
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(src, target)
        git(repo, "add", "--all")
        added = [ln[3:] for ln in git(repo, "status", "--porcelain").stdout.splitlines()]
        if not added:
            return False, [], False
        if dry_run:
            return True, added, False
        git(repo, "commit", "--quiet", "-m", message)
        git(repo, "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
        return True, added, True
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _AUTH = []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--remote", default=".")
    ap.add_argument("--branch", default="data")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restore", action="store_true", help="copy the data branch into --data instead of publishing")
    a = ap.parse_args(argv)
    remote = os.path.abspath(a.remote) if os.path.exists(a.remote) else a.remote
    if a.restore:
        print("restored earlier results from the data branch" if restore(a.data, remote, a.branch)
              else "no data branch yet: starting from nothing")
        return
    committed, changed, pushed = publish(a.data, remote, a.branch, a.dry_run)
    if not committed:
        print("nothing to commit: the data branch is already up to date")
    else:
        print(f"{'would commit' if a.dry_run else 'committed'} {len(changed)} changed path(s) to {a.branch}:")
        for c in changed[:20]:
            print(f"  {c}")
        print("pushed" if pushed else "not pushed (dry run)" if a.dry_run else "not pushed")


if __name__ == "__main__":
    sys.exit(main())
