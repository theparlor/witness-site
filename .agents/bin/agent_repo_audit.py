#!/usr/bin/env python3
"""Read-only safety checks shared by all coding-agent providers.

Generalized from one engagement repo's scripts/agent_repo_audit.py. Managed by
org-design-tooling/repo-kit; overwritten on every kit update. Standard: .agents/SESSIONS.md.

Read-only roots (external_read_only_roots in .agents/repository-policy.json) hold originals: filing
a new one is the point, editing an existing one is never done. Three changes are not edits and pass
(kit v16, 2026-09-28, purpose-oriented engagement folders): a byte-identical move that stays inside
the same root (a rename with 100% similarity), a deletion whose bytes remain at another path under
the same root (dropping an exact duplicate), and an edit to an index file (a basename listed in
read_only_root_index_files, CONTEXT.md by default) at any depth under the root. Kit 32 (WS-DDR-163 item 9,
2026-10-26) adds a fourth: a byte-identical rename out of the root that an applied reorganization record in the
same change names exactly (.intent/reorganizations/*/hashes*.json: the old and new path in `pairs`, the file's
sha256 in `before`), for a file filed there by mistake. An unrecorded move out still fails.

Only the change's own task record (the one naming the branch) counts as the change's own in the overlap check; a
record the change closes is not (kit 26). A task record with a live status whose worktree and branch are both gone is a stale lock (kit 24): it is
named in a warning at every land, and an ownership overlap it causes says so, with the fix. It still
counts in the overlap check, because a session on another machine has no worktree or branch here either.

Declared registers (csv_unique_key in the policy, kit 27): every CSV the change touches that matches a declared
glob must keep a unique key, must not carry its header again as a data row, and must not repeat a row under a
second key. A land whose rebase conflict covered a whole appended register pushed exactly that shape on 2026-09-26
(header swallowed as a data row, 31 rows renumbered and kept twice) while this audit reported no findings.
"""
import argparse, csv, fnmatch, hashlib, json, os, subprocess, sys
from pathlib import Path

def git(root, *args, check=True):
    return subprocess.run(["git", *args], cwd=root, check=check, text=True, capture_output=True).stdout

ROOT = Path(git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel").strip())
_pol = ROOT / ".agents/repository-policy.json"
POLICY = json.loads(_pol.read_text()) if _pol.exists() else {}
LIVE = {"planned", "active", "review-ready", "blocked"}

def match(path, pattern):
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.removeprefix("**/"))

def under(path, root):
    return path == root or path.startswith(root + "/")

def tasks():
    out = []
    legacy = ROOT / POLICY.get("task_registry", ".agents/tasks.json")
    if legacy.is_file():
        try: out += json.loads(legacy.read_text()).get("tasks", [])
        except Exception: pass
    d = ROOT / ".agents/tasks"
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            try: out.append(json.loads(f.read_text()))
            except Exception: pass
    return out

def branch_exists(branch):
    """A local branch or its remote-tracking copy."""
    return any(subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=ROOT, capture_output=True).returncode == 0
               for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"))

def stale(t):
    """A live record whose session left nothing behind on this machine: its worktree path and its branch are both
    gone (removed by hand, never `session finish`, which is what sets a record complete). It still joins the ownership
    check below, so it can block every land that touches its paths (kit 24). A session on another machine looks the
    same from here, which is why the check names it and never drops it."""
    if t.get("status") not in LIVE: return False
    wt, branch = str(t.get("worktree") or ""), str(t.get("branch") or "")
    if wt:
        p = Path(wt)
        common = Path(git(ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent
        if any(c.exists() for c in ([p] if p.is_absolute() else [ROOT / p, common / p, common.parent / p.name])): return False
    if branch and branch_exists(branch): return False
    return True

def recorded_moves():
    """(old, new, sha256 before) of every move an applied reorganization record lists (kit 32, WS-DDR-163 item 9): the
    `pairs` and `before` of .intent/reorganizations/*/hashes*.json, the record purpose-restructure.py apply writes."""
    out = set()
    for f in sorted((ROOT / ".intent" / "reorganizations").glob("*/hashes*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        before = rec.get("before") or {}
        for pair in rec.get("pairs") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] in before:
                out.add((pair[0], pair[1], before[pair[0]]))
    return out

def file_sha256(path):
    try:
        return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    except OSError:
        return ""

def head_blobs(root):
    """Blob ids of every tracked path under a read-only root at HEAD."""
    out = set()
    for line in git(ROOT, "ls-tree", "-r", "HEAD", "--", root, check=False).splitlines():
        meta = line.split("\t", 1)[0].split()
        if len(meta) == 3: out.add(meta[2])
    return out

def csv_rules():
    """The declared registers: each entry a glob (key in the first column) or {"glob": ..., "key_column": n}."""
    out = []
    for e in POLICY.get("csv_unique_key", []):
        if isinstance(e, str): out.append((e, 0))
        elif isinstance(e, dict) and isinstance(e.get("glob"), str):
            out.append((e["glob"], int(e.get("key_column", 0))))
    return out

def csv_findings(path, keycol):
    """Findings for one declared register; empty when it passes. Three shapes, each one a bad merge leaves:
    the header again as a data row (judged on the cells beside the key, because a resolver may renumber it),
    a key used twice, and one row kept twice under two keys."""
    try:
        with open(path, newline="", encoding="utf-8") as fh: rows = list(csv.reader(fh))
    except Exception as e:
        return [f"unreadable: {e}"]
    rows = [r for r in rows if r]
    if not rows: return []
    header, out, keys, bodies = rows[0], [], {}, {}
    rest = [c for i, c in enumerate(header) if i != keycol]
    for n, r in enumerate(rows[1:], start=2):
        others = [c for i, c in enumerate(r) if i != keycol]
        if r == header or (rest and sum(a == b for a, b in zip(others, rest)) * 2 >= len(rest)):
            out.append(f"line {n}: the header repeated as a data row"); continue
        k = r[keycol] if len(r) > keycol else ""
        if k in keys: out.append(f"line {n}: duplicate key {k!r} (first at line {keys[k]})")
        else: keys[k] = n
        body = tuple(others)
        if any(body) and body in bodies: out.append(f"line {n}: row {k!r} repeats line {bodies[body]} under another key")
        else: bodies.setdefault(body, n)
    return out

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--path", action="append", default=[], help="limit --check to an owned path/prefix")
    p.add_argument("--against", help="also check paths this branch changed relative to REF (e.g. origin/main)")
    a = p.parse_args()
    if not (a.preflight or a.check): p.error("choose --preflight or --check")
    branch = git(ROOT, "branch", "--show-current").strip() or "(detached)"
    status = git(ROOT, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    changed = [line[3:] for line in status if len(line) > 3]
    # paths whose existing content changed (modified, deleted, renamed); additions are not in here
    altered = {line[3:].split(" -> ")[0] for line in status if len(line) > 3 and line[:2].strip() and line[:2] not in ("??", "A ", "AM")}
    moved, deleted = {}, set()   # committed renames old -> (new, similarity); committed deletions
    if a.against:
        changed = sorted(set(changed) | set(x for x in git(ROOT, "diff", "--name-only", f"{a.against}...HEAD", check=False).split("\n") if x))
        for line in git(ROOT, "diff", "--name-status", f"{a.against}...HEAD", check=False).splitlines():
            parts = line.split("\t")
            if len(parts) < 2: continue
            kind = parts[0][:1]
            if kind == "R" and len(parts) > 2:
                moved[parts[1]] = (parts[2], int(parts[0][1:] or 0))
                altered.add(parts[1])
            elif kind == "D":
                deleted.add(parts[1]); altered.add(parts[1])
            elif kind in "MT":
                altered.add(parts[1])
    if a.path:
        changed = [x for x in changed if any(x == q.rstrip("/") or x.startswith(q.rstrip("/") + "/") for q in a.path)]
    errors, warnings, notes = [], [], []
    linked = Path(git(ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent.resolve() != ROOT.resolve()
    if a.preflight:
        if changed: warnings.append(f"worktree has {len(changed)} changed paths; treat them as user-owned")
        if not linked: warnings.append("this is the primary checkout; start a session: python3 .agents/bin/session start <task>")
    if a.check:
        diff_args = ["git", "diff", "--check"] + (["--", *a.path] if a.path else [])
        dc = subprocess.run(diff_args, cwd=ROOT, text=True, capture_output=True)
        if dc.returncode: errors.append("git diff --check failed: " + dc.stdout.strip()[:600])
        index_names = set(POLICY.get("read_only_root_index_files", ["CONTEXT.md"]))
        for root in POLICY.get("external_read_only_roots", []):
            # filing a new original is the point of these roots; changing an existing one is not.
            # An index (CONTEXT.md by default, at the root or at any depth under it) is not an original:
            # filing anything requires editing it, so it is exempt. A byte-identical move inside the
            # root and a deletion whose bytes remain elsewhere under the root are not edits either.
            index_files = {root + "/" + n for n in index_names}
            blobs = None
            recorded = None
            hits = []
            for x in sorted(altered):
                if not under(x, root): continue
                if x in index_files or os.path.basename(x) in index_names: continue
                if x in moved:
                    new, sim = moved[x]
                    if sim == 100 and under(new, root): continue
                    # kit 32: an original leaves the root only in a recorded reorganization: the change carries an
                    # applied record naming this exact move, and the bytes that arrive hash to the recorded value
                    if sim == 100:
                        if recorded is None: recorded = recorded_moves()
                        if any(o == x and n == new and h == file_sha256(new) for o, n, h in recorded): continue
                if x in deleted and a.against:
                    if blobs is None: blobs = head_blobs(root)
                    blob = git(ROOT, "rev-parse", "--verify", "--quiet", f"{a.against}:{x}", check=False).strip()
                    if blob and blob in blobs: continue
                hits.append(x)
            if hits: errors.append(f"external read-only paths modified, deleted or renamed under {root}: {', '.join(hits[:8])}")
        for m in POLICY.get("generator_maps", []):
            output = any(match(x, pat) for x in changed for pat in m["outputs"])
            source = any(x in m["sources"] for x in changed)
            if output and not source: errors.append(f"generated output lacks source change: {m['name']}")
        for pat in POLICY.get("non_durable_path_literals", []):
            for x in changed:
                f = ROOT / x
                if x == ".agents/repository-policy.json": continue
                if f.suffix not in POLICY.get("non_durable_path_scan_suffixes", []) or not f.is_file(): continue
                if pat in f.read_text(errors="ignore"):
                    errors.append(f"non-durable path literal {pat!r} in {x}: a session scratch directory does not outlive its session")
        rules = csv_rules()
        if rules:
            checked = 0
            for x in changed:
                rule = next((r for r in rules if match(x, r[0])), None)
                if rule is None or not (ROOT / x).is_file(): continue
                checked += 1
                found = csv_findings(ROOT / x, rule[1])
                if found:
                    errors.append(f"csv_unique_key: {x} has {len(found)} finding(s): " + "; ".join(found[:5]) +
                                  ("" if len(found) <= 5 else f"; and {len(found) - 5} more"))
            notes.append(f"csv_unique_key: {checked} declared register(s) in this change checked")
        if changed and not any(x.startswith(".agents/handoffs/") for x in changed):
            warnings.append("no task handoff is present in the change set")
        # Only an overlap involving this change's own task blocks; older overlaps are reported, not fatal.
        # This change's own record: the one naming the branch checked out here (kit 26). Until then every record the
        # change touched counted as its own, so a session closing another record (status complete in this change)
        # overlapped the record it was closing whenever that record claimed `.agents` (Turnberry, 2026-10-07). With
        # no record naming the branch, the touched records still live in this tree, never one being closed.
        touched = {}
        for x in changed:
            if x.startswith(".agents/tasks/") and x.endswith(".json") and (ROOT / x).is_file():
                try: touched[Path(x).stem] = json.loads((ROOT / x).read_text())
                except Exception: pass
        mine = {k for k, t in touched.items() if branch != "(detached)" and t.get("branch") == branch}
        if not mine:
            mine = {k for k, t in touched.items() if t.get("status") in LIVE}
        active = [t for t in tasks() if t.get("status") in LIVE or t.get("id") in mine]
        stale_ids = {t.get("id") for t in active if t.get("id") not in mine and stale(t)}
        for t in active:
            if t.get("id") in stale_ids:
                warnings.append(f"stale task record {t['id']} (status {t['status']}): its worktree {t.get('worktree') or '(none)'} "
                                f"and branch {t.get('branch') or '(none)'} are gone, and it still joins the ownership check at every "
                                "land; once you are sure no session on another machine owns it, set its status complete in a "
                                "session of its own")
        for i, left in enumerate(active):
            for right in active[i + 1:]:
                for lp in left.get("owned_paths", []):
                    for rp in right.get("owned_paths", []):
                        if lp == rp or lp.startswith(rp.rstrip("/") + "/") or rp.startswith(lp.rstrip("/") + "/"):
                            msg = f"task ownership overlap: {left['id']} and {right['id']} at {lp} / {rp}"
                            for sid in (left.get("id"), right.get("id")):
                                if sid in stale_ids:
                                    msg += (f" ({sid} is a stale record: its worktree and branch are gone; set its status "
                                            "complete in a session of its own, then land again)")
                            (errors if (mine and {left.get('id'), right.get('id')} & mine) else warnings).append(msg)
    print(f"repository: {ROOT}\nbranch: {branch}\nchanged paths: {len(changed)}")
    for x in notes: print("checked:", x)
    for x in errors: print("ERROR:", x)
    for x in warnings: print("WARNING:", x)
    if not errors and not warnings: print("OK: no findings")
    return bool(errors)

if __name__ == "__main__": sys.exit(main())
