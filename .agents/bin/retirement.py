#!/usr/bin/env python3
"""Retiring a session worktree: everything it holds goes onto a pushed archive tag, a ledger row and a manifest
land on main, then the worktree is removed. Stdlib only, Python 3.9 safe. Managed by org-design-tooling/repo-kit;
overwritten on every kit update.

One routine and one record format, shared by two callers (kit 29):
  - `session retire [--reason TEXT]`, the manual path for abandoned or superseded work;
  - the worktree reaper (org-design-tooling repo-kit/worktree_reaper.py), which imports this file from the kit for
    its landed retirements (the manifest, ledger, tag and removal helpers) and calls retire() itself for a robot's
    worktree that a later run of the same robot superseded.

Why (2026-10-23): sessions end before `session land` (killed, rate-limited, a person walked away, a scheduled job
failed). Their commits existed only on this machine's disk, and the reaper rightly refused to remove them, so
twenty worktrees sat 3 to 20 days, one holding the only copy of a client chat extract. Retiring keeps everything
and makes it recoverable from anywhere: the tag is on origin.

retire() in order, refusing before it changes anything:
  1. the worktree must be a linked worktree of `primary`, with no rebase, merge, cherry-pick, revert or bisect in
     progress and nothing kept aside by a stopped `session land` (session-kept);
  2. no uncommitted file over 100 MB (MAX_FILE_BYTES): GitHub refuses one, so each is named and nothing is done;
  3. ignored files outside the regenerable set (.venv, node_modules, caches) are moved to the primary when it has
     none there; where the primary holds a different copy, the newer of the two takes the primary's path and the
     older goes into an archive kept beside the record (keep_aside, kit 31); only more ignored bytes than
     LARGE_IGNORED_BYTES to compare refuses, naming the paths;
  4. the task record naming the branch is set to status "retired", then everything uncommitted (`git add -A`,
     ignored files excepted) becomes one snapshot commit on the branch, built with a temporary index and
     commit-tree like the reaper's record commit, so no hook can leave it half staged; it is an archive commit and
     never lands on main;
  5. the tip is tagged archive/<branch>-<date> and the tag pushed; a ledger row and a manifest are landed on
     origin/<base> as one commit built without a checkout (a pull request where the base branch requires one);
  6. the ignored files are moved, `git worktree remove` runs WITHOUT --force, the local branch is deleted only when
     the tag pins exactly its tip, and the branch's backup ref refs/wip/<branch> on origin is deleted.
An origin GitHub has archived (read-only) refuses the tag push: the tag stays local, and the ledger row and manifest
land in the Workspaces root's .intent/retirements/ instead (the first ancestor of the repository that is a git
checkout, or $WORKSPACES_ROOT), so a retirement there neither fails nor repeats.
"""
import filecmp
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

GIT_TIMEOUT = 120
MAX_FILE_BYTES = 100 * 1024 * 1024  # GitHub refuses a file over 100 MB
KEEP_ASIDE_SLACK_S = 60  # copies modified within a minute of each other count as the same age: the primary's stays
LARGE_IGNORED_BYTES = 2 << 30  # comparing more ignored bytes than this against the primary is left to a person
LEDGER = ".intent/retirements/LEDGER.md"
RESIDUE = ".agents/residue"
STATE_DIR = "worktree-reaper"  # under the primary's .git: pending PR records, the temporary index
WIP_NS = "refs/wip/"  # the backup ref namespace (kit 29): pushed on every commit, triggers no workflow, is no branch
IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply")
DROP_PARTS = {".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".claude"}
DROP_PREFIXES = (".entire/tmp/", ".entire/logs/")
DROP_NAMES = {".DS_Store"}
ARCHIVED_RE = re.compile(r"archived|read-only", re.I)
LEDGER_HEAD = """---
title: Retirement ledger
type: reference
maturity: living
created: {date}
---
# Retirement ledger

Every branch, stash, or worktree deliberately discarded from this repo, with a pointer to the tag that still holds it
and a manifest of what it contained. Nothing listed here is gone: recover any row with the command in its manifest.
Grep this directory before concluding that anything was lost.

"""
TABLE_HEAD = ("| Retired | Name | Kind | Holds it | Tip | Last real commit | Unique commits | Files | Why | Manifest |\n"
              "|---|---|---|---|---|---|---|---|---|---|\n")
RESIDUE_CONTEXT = """---
title: Worktree residue
type: reference
maturity: living
created: {date}
---
# Worktree residue

Hook output and session records that sat uncommitted in a worktree when the worktree was retired. Nothing here is work
product; it is kept because captured data is never destroyed. One folder per retired worktree, named for the worktree.
The retirement record for each worktree is in `.intent/retirements/` (grep the worktree name there).

| File | What it is |
|---|---|
| `<worktree>/<task>.json`, `<worktree>/<task>.md` | A session kit task record or handoff the session never committed (a session that started and never landed). |
| `<worktree>/forge-hook-probe.log.diff` | The lines a Forge hook probe appended to the tracked `.forge-hook-probe.log` in that worktree, as a patch against the worktree's HEAD. |
| `<worktree>/forge-hook-probe.log` | The same probe's log where the repo does not track it, copied verbatim. |

Session-end event lines from the same worktrees are not here: they were appended to the same `.intent/events/` file in
the primary checkout.
"""
REAPER_INTRO = ("The hourly worktree reaper (org-design-tooling `repo-kit/worktree_reaper.py`, LaunchAgent "
                "com.brien.worktree-reaper) retired these linked worktrees of this repo. Each one's work was already on "
                "main, nothing had touched it within the idle window, and no running process or recent Claude session "
                "was using it. Nothing was lost: each tip is pinned by a pushed archive tag, and each uncommitted file "
                "was kept as listed. The worktree folder and its local branch were removed after this record landed.\n")
RETIRE_INTRO = ("These worktrees were retired with their work NOT on main: abandoned, superseded, or a robot's run that a "
                "later run replaced (session kit `retire`, kit 29). Nothing was lost: everything uncommitted was folded "
                "into a snapshot commit, the tip is pinned by an archive tag, and the recover command below brings the "
                "branch back. The worktree folder and its local branch were removed after this record landed.\n")


class OriginArchived(RuntimeError):
    """The origin refused a push because GitHub archived the repository (read-only)."""


def git(cwd, *a, timeout=GIT_TIMEOUT, env=None):
    """(rc, stdout without its trailing newline, stderr stripped). Never raises."""
    try:
        r = subprocess.run(["git", *a], cwd=str(cwd), text=True, capture_output=True, timeout=timeout, env=env)
        return r.returncode, r.stdout.rstrip("\n"), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"git {a[0] if a else ''} timed out after {timeout}s"
    except OSError as e:
        return 127, "", f"git: {e}"


def git_bytes(cwd, *a, data=None, env=None):
    """(rc, stdout bytes). Never raises."""
    try:
        r = subprocess.run(["git", *a], cwd=str(cwd), input=data, capture_output=True, timeout=GIT_TIMEOUT, env=env)
        return r.returncode, r.stdout
    except (subprocess.TimeoutExpired, OSError):
        return 1, b""


def tilde(p):
    """A path for a record: the account home written as ~, so no tracked file names it (the portability check)."""
    s, home = str(p), str(Path.home())
    return "~" + s[len(home):] if s == home or s.startswith(home + os.sep) else s


def default_branch(repo):
    rc, out, _ = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return out.split("/", 1)[1] if rc == 0 and "/" in out else "main"


def gitdir_of(wt):
    rc, out, _ = git(wt, "rev-parse", "--path-format=absolute", "--git-dir")
    return Path(out) if rc == 0 and out else None


def workspaces_root(start):
    """$WORKSPACES_ROOT, else the first ancestor of `start` (not `start` itself) holding a .git directory."""
    env = os.environ.get("WORKSPACES_ROOT", "").strip()
    if env and (Path(env) / ".git").is_dir():
        return Path(env).resolve()
    for p in list(Path(start).resolve().parents):
        if (p / ".git").is_dir():
            return p
    return None


# ---------------------------------------------------------------------------------------------------------------
# Pushing, tags and the backup ref

def push(cwd, *refspecs, timeout=GIT_TIMEOUT):
    """Push to origin. Raises OriginArchived when GitHub refuses because the repository is archived, RuntimeError
    for any other refusal."""
    rc, _, err = git(cwd, "push", "-q", "origin", *refspecs, timeout=timeout)
    if rc == 0:
        return
    msg = " ".join(err.split())
    if ARCHIVED_RE.search(msg):
        raise OriginArchived(f"origin is archived (read-only): {msg[:200]}")
    raise RuntimeError(f"push {' '.join(refspecs)}: {msg[:200]}")


def tag_name(branch, folder, date):
    return f"archive/{branch}-{date}" if branch else f"archive/detached-{folder}-{date}"


def ensure_tag(primary, tag, sha):
    """Create (or reuse when it already pins `sha`) the archive tag and push it. Returns the tag actually used.
    Raises OriginArchived with .tag set when origin is read-only: the tag then exists locally only."""
    name, n = tag, 1
    while True:
        rc, have, _ = git(primary, "rev-parse", "-q", "--verify", f"refs/tags/{name}^{{commit}}")
        if rc or not have:
            rc, _, err = git(primary, "tag", name, sha)
            if rc:
                raise RuntimeError(f"tag {name}: {err[:200]}")
            break
        if have == sha:
            break
        n += 1
        name = f"{tag}-{n}"
    try:
        push(primary, f"refs/tags/{name}")
    except OriginArchived as e:
        e.tag = name
        raise
    return name


def wip_ref(branch):
    return WIP_NS + branch


def drop_wip(cwd, branch, timeout=60):
    """Delete the branch's backup ref on origin (kit 29). True when it is gone or never existed. Never raises."""
    if not branch:
        return True
    rc, _, err = git(cwd, "push", "-q", "origin", f":{wip_ref(branch)}", timeout=timeout)
    return rc == 0 or "remote ref does not exist" in err or "unable to delete" in err


def wip_heads(cwd, timeout=60):
    """{branch: sha} of every backup ref on origin, or None when origin cannot be asked."""
    rc, out, _ = git(cwd, "ls-remote", "origin", f"{WIP_NS}*", timeout=timeout)
    if rc:
        return None
    heads = {}
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.startswith(WIP_NS):
            heads[ref[len(WIP_NS):]] = sha
    return heads


# ---------------------------------------------------------------------------------------------------------------
# The record: manifest, ledger rows, residue, landed as one commit with no checkout

def commit_info(wt, base):
    up = f"origin/{base}"
    _, last, _ = git(wt, "log", "-1", "--format=%cs", "HEAD")
    _, mb, _ = git(wt, "merge-base", "HEAD", up)
    _, commits, _ = git(wt, "log", "--format=%h %cs %s", f"{up}..HEAD")
    files = []
    if mb:
        _, out, _ = git(wt, "diff", "--name-only", "--no-renames", "-z", mb, "HEAD")
        files = [p for p in out.split("\0") if p]
    return {"last": last, "commits": [c for c in commits.splitlines() if c], "files": files}


def empty_residue():
    return {"shard": [], "record": [], "probe": [], "on_main": [], "carry": [], "dup": [], "replace": [], "aside": [],
            "dropped": 0, "work": [], "snapshot": []}


def residue_count(r):
    return sum(len(r.get(k, [])) for k in ("shard", "record", "probe", "carry", "snapshot"))


def manifest_section(c):
    w, info, r = c["wt"], c["info"], c["residue"]
    kept = []
    if r.get("snapshot"):
        kept.append(f"{len(r['snapshot'])} uncommitted path(s) folded into the snapshot commit the tag pins: "
                    + ", ".join(f"`{p}`" for p in r["snapshot"][:20]) + (" and more" if len(r["snapshot"]) > 20 else ""))
    if r.get("shard"):
        kept.append(f"{len(r['shard'])} session event file(s) appended to the same path in the primary checkout")
    if r.get("record"):
        kept.append(f"{len(r['record'])} uncommitted session record(s) or hook log(s) landed in "
                    f"{RESIDUE}/{w['path'].name}/")
    if r.get("probe"):
        kept.append(f"the Forge hook probe log's lines landed as {RESIDUE}/{w['path'].name}/forge-hook-probe.log.diff")
    if r.get("carry"):
        kept.append(f"{len(r['carry'])} gitignored file(s) moved to the same path in the primary checkout: "
                    + ", ".join(f"`{p}`" for p in r["carry"][:20]) + (" and more" if len(r["carry"]) > 20 else ""))
    if r.get("replace") or r.get("aside"):
        kept.append(f"{len(r.get('replace', []))} gitignored file(s) newer in the worktree took their place in the "
                    f"primary checkout and {len(r.get('aside', []))} older worktree copy(ies) were set aside; every "
                    f"copy that lost its place is in `{c.get('aside_archive', '')}` (local, excluded from git; "
                    "replaced-in-primary/ and from-worktree/ inside)")
    if r.get("on_main") or r.get("dup"):
        kept.append(f"{len(r.get('on_main', [])) + len(r.get('dup', []))} file(s) already identical on main or in "
                    "the primary")
    branch = w["branch"] or "DETACHED"
    recover = (f"git checkout -b {w['branch']} {c['tag']}" if w["branch"] else f"git checkout --detach {c['tag']}")
    lines = [f"## {w['path'].name}", ""]
    if c.get("repo_note"):
        lines.append(f"- Repository: {c['repo_note']}")
    lines += [f"- Path: `{tilde(w['path'])}` ({c['kind']} worktree)",
              f"- Branch: `{branch}`, tip `{w['head'][:8]}`, last commit {info['last'] or 'unknown'}",
              f"- Tag: `{c['tag']}`" + (" (local to this machine's clone: origin is archived)" if c.get("archived") else ""),
              f"- Landing on main: {c['how']}"]
    if c.get("why_retired"):
        lines.append(f"- Why retired: {c['why_retired']}")
    if c.get("idle_h") is not None:
        lines.append(f"- Idle: {c['idle_h']:.1f} hours when retired")
    lines += ["- Residue: " + ("; ".join(kept) if kept else "nothing uncommitted"),
              "- Commits not on main by hash:" + ("" if info["commits"] else " none")]
    lines += [f"  - {x}" for x in info["commits"][:50]]
    lines.append("- Files those commits touched:" + ("" if info["files"] else " none"))
    lines += [f"  - `{f}`" for f in info["files"][:100]]
    if len(info["files"]) > 100:
        lines.append(f"  - and {len(info['files']) - 100} more (`git diff --stat` against the tag)")
    lines += [f"- Recover: `{recover}`", ""]
    return "\n".join(lines)


def build_record(primary, base, cands, date, stamp, source="worktree-reaper", intro=None):
    """{repo-relative path: function(origin's bytes or None) -> new bytes} for the one record commit."""
    name = f"RET-{date}-{source}-{stamp}.md"
    label = "Worktree reaper pass" if source == "worktree-reaper" else "Worktree retirement"
    body = [f"---\ntitle: {label} {date} {stamp[:2]}:{stamp[2:]}\ntype: retirement-manifest\n"
            f"maturity: final\ncreated: {date}\n---\n",
            f"# {label}, {date} {stamp[:2]}:{stamp[2:]}\n",
            intro or REAPER_INTRO]
    body += [manifest_section(c) for c in cands]
    text = "\n".join(body)
    files = {f".intent/retirements/{name}": lambda cur: text.encode()}
    rows = []
    for c in cands:
        n = residue_count(c["residue"])
        why = c.get("why") or (f"Worktree reaper: {c['kind']} worktree, work on main ({c['how']}), idle "
                               f"{c['idle_h']:.0f} h" + (f"; residue kept ({n} path(s))" if n else ""))
        rows.append(f"| {date} | {c.get('name') or c['wt']['path'].name} | worktree | tag `{c['tag']}` | "
                    f"{c['wt']['head'][:8]} | {c['info']['last']} | {len(c['info']['commits'])} | "
                    f"{len(c['info']['files'])} | {why}. | [{name}]({name}) |")

    def ledger(cur):
        doc = cur.decode("utf-8", "surrogateescape") if cur else LEDGER_HEAD.format(date=date)
        if not doc.endswith("\n"):
            doc += "\n"
        last = next((l for l in reversed(doc.splitlines()) if l.strip()), "")
        if not last.startswith("|"):
            doc += ("\n" if doc.strip() and not doc.endswith("\n\n") else "") + TABLE_HEAD
        return (doc + "\n".join(rows) + "\n").encode("utf-8", "surrogateescape")
    files[LEDGER] = ledger
    any_residue = False
    for c in cands:
        wt, folder = c["wt"]["path"], f"{RESIDUE}/{c['wt']['path'].name}"
        for rel in c["residue"].get("record", []):
            data = (Path(wt) / rel).read_bytes()
            dest = f"{folder}/{Path(rel).name.lstrip('.')}"
            files[dest] = lambda cur, d=data: d
            c.setdefault("landed_residue", []).append((rel, dest, data))
            any_residue = True
        for rel in c["residue"].get("probe", []):
            _, diff = git_bytes(wt, "diff", "--no-ext-diff", "HEAD", "--", rel)
            files[f"{folder}/{Path(rel).name.lstrip('.')}.diff"] = lambda cur, d=diff: d
            any_residue = True
    if any_residue:
        files[f"{RESIDUE}/CONTEXT.md"] = lambda cur: cur if cur else RESIDUE_CONTEXT.format(date=date).encode()
    return files


def land_record(primary, base, files, message):
    """Land `files` as one commit on origin/<base> without touching any checkout. Returns ("pushed", sha),
    ("pr", url) when the base branch's rules require a pull request, or raises RuntimeError (OriginArchived when
    the repository is archived)."""
    gd = gitdir_of(primary)
    if gd is None:
        raise RuntimeError("cannot find the primary's git dir")
    state = gd / STATE_DIR
    state.mkdir(exist_ok=True)
    last = ""
    for _ in range(3):
        rc, _, err = git(primary, "fetch", "-q", "origin", base)
        if rc:
            raise RuntimeError(f"fetch origin {base}: {err[:200]}")
        idx = str(state / f"index-{os.getpid()}")
        env = dict(os.environ, GIT_INDEX_FILE=idx)
        up = f"origin/{base}"
        try:
            if git_bytes(primary, "read-tree", up, env=env)[0]:
                raise RuntimeError("read-tree failed")
            for rel, make in files.items():
                rc, cur = git_bytes(primary, "cat-file", "blob", f"{up}:{rel}")
                data = make(cur if rc == 0 else None)
                rc, sha = git_bytes(primary, "hash-object", "-w", "--stdin", data=data)
                if rc:
                    raise RuntimeError(f"hash-object {rel} failed")
                if git_bytes(primary, "update-index", "--add", "--cacheinfo",
                             f"100644,{sha.decode().strip()},{rel}", env=env)[0]:
                    raise RuntimeError(f"update-index {rel} failed")
            rc, tree = git_bytes(primary, "write-tree", env=env)
            if rc:
                raise RuntimeError("write-tree failed")
        finally:
            try:
                os.unlink(idx)
            except OSError:
                pass
        _, parent, _ = git(primary, "rev-parse", up)
        rc, commit, err = git(primary, "commit-tree", tree.decode().strip(), "-p", parent, "-m", message)
        if rc:
            raise RuntimeError(f"commit-tree failed: {err[:200]}")
        rc, _, err = git(primary, "push", "-q", "origin", f"{commit}:refs/heads/{base}")
        if rc == 0:
            return "pushed", commit
        last = " ".join(err.split())
        if ARCHIVED_RE.search(last):
            raise OriginArchived(f"origin is archived (read-only): {last[:200]}")
        if re.search(r"protected branch|GH006|GH013|rule violations|required status check|pull request", last, re.I):
            return "pr", open_pr(primary, base, commit, message)
        if not re.search(r"fetch first|non-fast-forward|rejected", last):
            break
    raise RuntimeError(f"push to {base} failed: {last[:200]}")


def open_pr(primary, base, commit, message):
    branch = f"reaper/{datetime.now().strftime('%Y-%m-%d-%H%M%S')}"
    rc, _, err = git(primary, "push", "-q", "origin", f"{commit}:refs/heads/{branch}")
    if rc:
        raise RuntimeError(f"push {branch}: {err[:200]}")
    try:
        r = subprocess.run(["gh", "pr", "create", "--head", branch, "--base", base, "--title", message.splitlines()[0],
                            "--body", message + "\n\nOpened by the worktree reaper because this branch's rules "
                            "require a pull request; the worktrees are removed on the run after it merges."],
                           cwd=str(primary), capture_output=True, text=True, timeout=120)
        url = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ""
        if not url:
            raise RuntimeError(f"gh pr create failed: {r.stderr.strip()[:200]}")
        subprocess.run(["gh", "pr", "merge", url, "--squash", "--auto", "--delete-branch"], cwd=str(primary),
                       capture_output=True, text=True, timeout=120)
        return url
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"gh: {e}")


def recorded(repo, base, tag):
    rc, ledger = git_bytes(repo, "cat-file", "blob", f"origin/{base}:{LEDGER}")
    return rc == 0 and f"`{tag}`".encode() in ledger


# ---------------------------------------------------------------------------------------------------------------
# Reading a worktree

def status(wt):
    """[(XY, path)] for every modified, staged, deleted or untracked path; never writes the index."""
    rc, out, err = git(wt, "--no-optional-locks", "status", "--porcelain", "-z", "--untracked-files=all")
    if rc:
        raise RuntimeError(f"git status failed: {err[:200]}")
    entries, fields, i = [], out.split("\0"), 0
    while i < len(fields):
        e = fields[i]
        i += 1
        if len(e) < 4:
            continue
        entries.append((e[:2], e[3:]))
        if "R" in e[:2] or "C" in e[:2]:
            if i < len(fields) and fields[i]:
                entries.append(("D ", fields[i]))  # the rename's source: a change in its own right
            i += 1
    return entries


def ignored(wt):
    """Ignored files and folders on disk, folders collapsed (".venv/")."""
    rc, out, _ = git(wt, "--no-optional-locks", "ls-files", "--others", "--ignored", "--exclude-standard",
                     "--directory", "-z")
    return [p for p in out.split("\0") if p] if rc == 0 else []


def dropping(rel):
    parts = rel.rstrip("/").split("/")
    return (bool(DROP_PARTS.intersection(parts)) or parts[-1] in DROP_NAMES or rel.endswith(".pyc")
            or any(rel.startswith(x) for x in DROP_PREFIXES))


def walk(wt, rel):
    """The files (and symlinks) under an ignored path git listed, repo-relative."""
    p = Path(wt) / rel.rstrip("/")
    if p.is_symlink() or not p.is_dir():
        return [rel.rstrip("/")]
    out = []
    for dirpath, dirnames, filenames in os.walk(p):
        for n in list(dirnames):
            if os.path.islink(os.path.join(dirpath, n)):
                filenames.append(n)
                dirnames.remove(n)
        for n in filenames:
            out.append(os.path.relpath(os.path.join(dirpath, n), wt))
    return out


def same_file(a, b):
    try:
        if os.path.islink(a) or os.path.islink(b):
            return os.path.islink(a) and os.path.islink(b) and os.readlink(a) == os.readlink(b)
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def ignored_plan(primary, wt):
    """{"carry", "dup", "replace", "aside": [...], "dropped": n, "work": [...]}: what happens to each ignored file.
    carry: moved to the primary, which has none there; dup: the primary's copy is identical; replace: the primary
    holds a different, older copy, so the worktree's takes its place and the older is archived; aside: the primary
    holds a different copy at least as new, so it stays and the worktree's is archived; dropped: regenerable; work:
    too much to compare (a person decides). Newer means a later modification time by more than KEEP_ASIDE_SLACK_S.
    Until kit 31 every different copy was work, and the copy kept in place was whichever was in the primary, so a
    newer build could end up archived while an older one stayed live (an engagement repo, 2026-10-23: 153 files)."""
    res = {"carry": [], "dup": [], "replace": [], "aside": [], "dropped": 0, "work": []}
    budget = 0
    for rel in ignored(wt):
        if dropping(rel):
            res["dropped"] += 1
            continue
        for f in walk(wt, rel):
            if dropping(f):
                res["dropped"] += 1
                continue
            mine, theirs = Path(wt) / f, Path(primary) / f
            if not os.path.lexists(theirs):
                res["carry"].append(f)
                continue
            try:
                budget += os.lstat(mine).st_size
            except OSError:
                pass
            if budget > LARGE_IGNORED_BYTES:
                res["work"].append(f"{f} (more than {LARGE_IGNORED_BYTES >> 30} GB of ignored files to compare)")
                return res
            if same_file(mine, theirs):
                res["dup"].append(f)
            elif newer(mine, theirs):
                res["replace"].append(f)
            else:
                res["aside"].append(f)
    return res


def newer(a, b):
    """True when `a` was modified more than KEEP_ASIDE_SLACK_S after `b`."""
    try:
        return os.lstat(a).st_mtime > os.lstat(b).st_mtime + KEEP_ASIDE_SLACK_S
    except OSError:
        return False


ASIDE_GLOB = "/.agents/residue/*/ignored-copies-*.tar.gz"


def aside_archive(primary, label, date):
    """Repo-relative path of the archive keep_aside() writes: one per worktree and day, never over an existing one."""
    base = f"{RESIDUE}/{label}"
    rel, n = f"{base}/ignored-copies-{date}.tar.gz", 2
    while (Path(primary) / rel).exists():
        rel, n = f"{base}/ignored-copies-{date}-{n}.tar.gz", n + 1
    return rel


def exclude_aside(primary, rel):
    """Keep the archive out of git in this clone (info/exclude in the common git dir), and prove it."""
    rc, common, _ = git(primary, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc:
        raise RuntimeError("could not find the primary's git dir to exclude the kept-aside archive")
    ex = Path(common) / "info" / "exclude"
    ex.parent.mkdir(parents=True, exist_ok=True)
    have = ex.read_text().splitlines() if ex.exists() else []
    if ASIDE_GLOB not in have:
        with open(ex, "a") as f:
            f.write(("\n" if have and not ex.read_text().endswith("\n") else "")
                    + "# session kit 31: copies of ignored files kept aside at retirement (local only)\n"
                    + ASIDE_GLOB + "\n")
    if git(primary, "check-ignore", "-q", "--no-index", rel)[0] != 0:
        raise RuntimeError(f"{rel} would not be ignored by git; nothing was changed")


def _digest(path):
    if os.path.islink(path):
        return "link:" + os.readlink(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def keep_aside(primary, wt, replace, aside, rel):
    """Of two different copies of an ignored file, the newer stays in place and the older is kept (kit 31; Brien,
    2026-10-23: "change the retire rule so the newer copy wins in place"). Every copy that loses its place is written
    to the archive `rel` in the primary and read back byte for byte BEFORE anything in the primary changes:
    replace: the primary's older copy goes in as replaced-in-primary/<path>, then the worktree's newer copy is moved
    into the primary (its modification time kept); aside: the worktree's older copy goes in as from-worktree/<path>
    and leaves with the worktree. Returns how many files took a new place. Raises RuntimeError when a copy cannot be
    confirmed or the primary's copy changed in the meantime; the primary is then as it was."""
    if not replace and not aside:
        return 0
    primary, wt = Path(primary), Path(wt)
    exclude_aside(primary, rel)
    members = ([(primary / r, f"replaced-in-primary/{r}") for r in replace]
               + [(wt / r, f"from-worktree/{r}") for r in aside])
    want = {name: _digest(src) for src, name in members}
    dest = primary / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with tarfile.open(part, "w:gz", format=tarfile.PAX_FORMAT) as t:
        for src, name in members:
            t.add(str(src), arcname=name, recursive=False)
    with tarfile.open(part) as t:
        for m in t.getmembers():
            got = ("link:" + m.linkname) if m.issym() else hashlib.sha256(t.extractfile(m).read()).hexdigest()
            if want.get(m.name) != got:
                part.unlink()
                raise RuntimeError(f"{m.name}: its copy in the archive does not match; nothing was changed")
        if len(t.getmembers()) != len(members):
            part.unlink()
            raise RuntimeError("the archive is missing copies; nothing was changed")
    os.replace(part, dest)
    placed = 0
    for r in replace:
        src, to = wt / r, primary / r
        if _digest(to) != want[f"replaced-in-primary/{r}"]:
            raise RuntimeError(f"{r}: the primary's copy changed after it was archived; both kept, worktree left")
        mine = _digest(src)
        try:
            os.replace(src, to)
        except OSError:
            shutil.copy2(src, to, follow_symlinks=False)
            os.unlink(src)
        if _digest(to) != mine:
            raise RuntimeError(f"{r}: the newer copy did not arrive intact; the older is in {rel}")
        placed += 1
    return placed


def carry_ignored(primary, wt, rels):
    """Move each ignored file to the same path in the primary. Returns how many moved; raises RuntimeError when the
    primary has since gained a different copy (both kept, the worktree left)."""
    moved = 0
    for rel in rels:
        src, dest = Path(wt) / rel, Path(primary) / rel
        if os.path.lexists(dest):
            if not same_file(src, dest):
                raise RuntimeError(f"{rel}: the primary now has a different copy; both kept, worktree left")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved += 1
    return moved


def inside(child, parent):
    c, p = os.path.realpath(child), os.path.realpath(parent)
    return c == p or c.startswith(p + os.sep)


def unlink_pruning(wt, rel):
    """Remove a kept file, then every folder it leaves empty up to the worktree. An emptied folder left behind reads
    as untracked to `git worktree remove` when core.untrackedCache is on (seen 2026-10-02 in three worktrees: the
    cache still remembered the folder's file), so removal refused a worktree whose status was otherwise empty."""
    path = Path(wt) / rel
    os.unlink(path)
    top, d = Path(wt).resolve(), path.parent
    while d.resolve() != top and inside(d, top):
        try:
            d.rmdir()
        except OSError:
            break
        d = d.parent


def empty_dir(p):
    """True for a real folder (not a link) with no file or link anywhere under it."""
    if p.is_symlink() or not p.is_dir():
        return False
    for dp, dirs, files in os.walk(p):
        if files or any(os.path.islink(os.path.join(dp, d)) for d in dirs):
            return False
    return True


def prune_empty(p):
    """Remove an empty folder tree, deepest first."""
    for d, _, _ in sorted(os.walk(p), key=lambda t: len(t[0]), reverse=True):
        try:
            os.rmdir(d)
        except OSError:
            pass


def du_mb(path):
    try:
        r = subprocess.run(["du", "-sk", str(path)], capture_output=True, text=True, timeout=600)
        return round(int(r.stdout.split()[0]) / 1024, 1)
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def remove_worktree(primary, wt, branch, tag):
    """Confirm the worktree is clean, `git worktree remove` it WITHOUT --force, then delete the local branch when
    the tag pins exactly its tip. Returns the MB freed (None when unmeasured); raises RuntimeError."""
    left = status(wt)
    # and the exact check `git worktree remove` makes (default untracked mode, which consults the untracked cache)
    rc, plain, _ = git(wt, "status", "--porcelain", "--ignore-submodules=none")
    if not left and plain:
        left = [(l[:2], l[3:]) for l in plain.splitlines()]
        # A folder that holds no file is nothing to keep: the untracked cache can list one for weeks after its
        # last file went (two landed worktrees errored every hour for a week, 2026-10-16 to 10-23). Remove it.
        if all(xy == "??" and empty_dir(Path(wt) / p) for xy, p in left):
            for _, p in left:
                prune_empty(Path(wt) / p)
            git(wt, "update-index", "--untracked-cache")
            _, plain, _ = git(wt, "-c", "core.untrackedCache=false", "status", "--porcelain", "--ignore-submodules=none")
            left = [(l[:2], l[3:]) for l in plain.splitlines()]
    if left:
        raise RuntimeError(f"{len(left)} path(s) still uncommitted after keeping the residue: "
                           + ", ".join(p for _, p in left[:5]))
    freed = du_mb(wt)
    rc, _, err = git(primary, "worktree", "remove", str(wt))
    if rc:
        raise RuntimeError(f"git worktree remove refused: {' '.join(err.split())[:200]}")
    if branch:
        _, tip, _ = git(primary, "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}")
        _, now, _ = git(primary, "rev-parse", "-q", "--verify", f"refs/heads/{branch}")
        if now and now == tip:  # the tag pins exactly what the branch holds
            git(primary, "branch", "-D", branch)
    return freed


# ---------------------------------------------------------------------------------------------------------------
# Retiring work that is not on main

def big_files(wt, entries, limit=MAX_FILE_BYTES):
    """[(path, MB)] of uncommitted files over `limit`."""
    out = []
    for _, rel in entries:
        p = Path(wt) / rel
        try:
            if p.is_file() and not p.is_symlink() and p.stat().st_size > limit:
                out.append((rel, round(p.stat().st_size / (1 << 20), 1)))
        except OSError:
            continue
    return out


def mark_task_retired(wt, branch, reason, when):
    """Set the task record naming `branch` to status "retired" before the snapshot, so the archived record says
    what happened. Returns the record's path relative to the worktree, or None."""
    d = Path(wt) / ".agents" / "tasks"
    if not branch or not d.is_dir():
        return None
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("branch") == branch:
            rec.update(status="retired", retired=when, retired_reason=reason)
            p.write_text(json.dumps(rec, indent=2) + "\n")
            return str(p.relative_to(wt))
    return None


def snapshot(wt, message):
    """Fold everything uncommitted (git add -A, ignored files excepted) into one commit on the worktree's HEAD.
    Built with a temporary index and commit-tree, then HEAD moved by compare-and-swap and the real index set to the
    new tree (the working files already match it), so a failure at any step leaves the worktree as it was.
    Returns the new commit, or None when nothing was uncommitted."""
    gd = gitdir_of(wt)
    if gd is None:
        raise RuntimeError("cannot find the worktree's git dir")
    _, head, _ = git(wt, "rev-parse", "HEAD")
    idx = str(gd / f"retire-index-{os.getpid()}")
    env = dict(os.environ, GIT_INDEX_FILE=idx)
    try:
        for args in (("read-tree", "HEAD"), ("add", "-A")):
            rc, _, err = git(wt, *args, env=env)
            if rc:
                raise RuntimeError(f"git {' '.join(args)} failed: {err[:200]}")
        rc, tree, err = git(wt, "write-tree", env=env)
        if rc:
            raise RuntimeError(f"write-tree failed: {err[:200]}")
    finally:
        try:
            os.unlink(idx)
        except OSError:
            pass
    _, head_tree, _ = git(wt, "rev-parse", "HEAD^{tree}")
    if tree == head_tree:
        return None
    rc, sha, err = git(wt, "commit-tree", tree, "-p", head, "-m", message)
    if rc:
        raise RuntimeError(f"commit-tree failed: {err[:200]}")
    rc, _, err = git(wt, "update-ref", "-m", "retire: snapshot of uncommitted work", "HEAD", sha, head)
    if rc:
        raise RuntimeError(f"update-ref failed: {err[:200]}")
    for args in (("read-tree", sha), ("update-index", "-q", "--refresh")):
        git(wt, *args)
    return sha


def retire(primary, wt, *, base=None, reason="", source="session-retire", kind="kit", how=None, idle_h=None,
           dry_run=False, root=None, now=None):
    """Retire one linked worktree whose work may not be on main. Returns a dict: action (retired, would-retire,
    refused, error), reason, tag, snapshot (paths folded in), archived, route, freed_mb, moved_files, wip_dropped.
    Never raises for a refusal: the dict says why and nothing was changed."""
    primary, wt = Path(primary), Path(wt)
    base = base or default_branch(primary)
    rec = {"action": "refused", "reason": "", "worktree": str(wt), "tag": None, "snapshot": [], "archived": False}
    if not wt.is_dir() or os.path.realpath(wt) == os.path.realpath(primary):
        rec["reason"] = "not a linked worktree of this repository (the primary checkout is never retired)"
        return rec
    gd = gitdir_of(wt)
    busy = [m for m in IN_PROGRESS if gd and (gd / m).exists()]
    if busy:
        rec["reason"] = "an operation is in progress: " + ", ".join(busy) + "; finish or abort it first"
        return rec
    kept = gd / "session-kept" if gd else None
    if kept and kept.is_dir() and any(kept.iterdir()):
        rec["reason"] = (f"a stopped session land kept copies in {kept}; run `session land` to put them back, "
                         "then retire")
        return rec
    rc, branch, _ = git(wt, "symbolic-ref", "--short", "-q", "HEAD")
    branch = branch if rc == 0 and branch else None
    rec["branch"] = branch or ""
    try:
        entries = status(wt)
    except RuntimeError as e:
        rec["action"], rec["reason"] = "error", str(e)
        return rec
    big = big_files(wt, entries)
    if big:
        rec["reason"] = ("files over 100 MB, which GitHub refuses, are not snapshotted; move them out of the worktree "
                         "(or into git LFS) first: " + ", ".join(f"{p} ({mb} MB)" for p, mb in big))
        return rec
    plan = ignored_plan(primary, wt)
    if plan["work"]:
        rec["reason"] = ("too many ignored bytes to compare against the primary (a person decides which copies to "
                         "keep): " + ", ".join(plan["work"][:8]))
        return rec
    rec["snapshot"] = sorted({p for _, p in entries})
    if dry_run:
        rec["action"] = "would-retire"
        rec["reason"] = (reason or "retired") + f"; {len(rec['snapshot'])} uncommitted path(s) to snapshot"
        if plan["replace"] or plan["aside"]:
            rec["reason"] += (f"; {len(plan['replace'])} newer ignored copy(ies) would take the primary's place and "
                              f"{len(plan['aside'])} older one(s) would be set aside, both sides archived")
        return rec
    os.environ["SESSION_WIP_BACKUP"] = "0"  # this process's own commits push no backup ref
    when = datetime.fromtimestamp(now) if now else datetime.now()
    date = when.strftime("%Y-%m-%d")
    try:
        mark_task_retired(wt, branch, reason, when.astimezone().isoformat(timespec="seconds"))
        rec["snapshot"] = sorted({p for _, p in status(wt)})
        snap = snapshot(wt, f"retire: snapshot of uncommitted work in {wt.name}\n\n{reason or 'retired'}\n\n"
                            "Folded in by the session kit's retire routine (kit 29) so nothing is lost; this commit "
                            "never lands on main. Recover from the archive tag.") if rec["snapshot"] else None
        _, head, _ = git(wt, "rev-parse", "HEAD")
        tag = tag_name(branch, wt.name, date)
        archived = False
        try:
            tag = ensure_tag(primary, tag, head)
        except OriginArchived as e:
            tag, archived = getattr(e, "tag", tag), True
        rec.update(tag=tag, archived=archived, snapshot_commit=snap or "")
        residue = empty_residue()
        residue["snapshot"], residue["carry"], residue["dup"] = rec["snapshot"], plan["carry"], plan["dup"]
        residue["replace"], residue["aside"] = plan["replace"], plan["aside"]
        aside_rel = aside_archive(primary, wt.name, date) if plan["replace"] or plan["aside"] else None
        w = {"path": wt, "branch": branch, "head": head}
        c = {"wt": w, "kind": kind, "how": how or "not on main", "idle_h": idle_h, "residue": residue, "tag": tag,
             "info": commit_info(wt, base), "why_retired": reason or "retired by hand", "archived": archived,
             "aside_archive": aside_rel,
             "why": f"Retired, work not on main: {reason or 'retired by hand'}"
                    + (f"; {len(rec['snapshot'])} uncommitted path(s) in its snapshot" if rec["snapshot"] else "")}
        stamp = when.strftime("%H%M")
        message = (f"retire: {wt.name}, work not on main, kept on {tag}\n\n{reason or 'retired by hand'}")
        if archived:
            ws = Path(root) if root else workspaces_root(primary)
            if ws is None or os.path.realpath(ws) == os.path.realpath(primary):
                raise RuntimeError("origin is archived and no Workspaces root was found to hold the ledger row; the "
                                   f"tag {tag} is local; nothing else was changed")
            rel = os.path.relpath(primary, ws)
            c["repo_note"] = (f"`{rel}` (its origin on GitHub is archived, read-only, so the tag lives only in this "
                              "machine's clone and this record is kept in the Workspaces root)")
            c["name"] = f"{Path(rel).name}/{wt.name}"
            route, ref = land_record(ws, default_branch(ws), build_record(ws, default_branch(ws), [c], date, stamp,
                                                                           source=source, intro=RETIRE_INTRO), message)
        else:
            route, ref = land_record(primary, base, build_record(primary, base, [c], date, stamp, source=source,
                                                                 intro=RETIRE_INTRO), message)
        rec.update(route=route, record=ref)
        rec["newer_placed"] = keep_aside(primary, wt, plan["replace"], plan["aside"], aside_rel) if aside_rel else 0
        rec["kept_aside"] = aside_rel or ""
        rec["moved_files"] = carry_ignored(primary, wt, plan["carry"])
        rec["freed_mb"] = remove_worktree(primary, wt, branch, tag)
        rec["wip_dropped"] = False if archived else drop_wip(primary, branch)
        rec["action"] = "retired"
        rec["reason"] = reason or "retired by hand"
    except (RuntimeError, OSError) as e:
        rec["action"], rec["reason"] = "error", str(e)[:400]
    return rec
