#!/usr/bin/env python3
"""Read-only safety checks shared by all coding-agent providers.

Generalized from the Subaru engagement's scripts/agent_repo_audit.py. Managed by
org-design-tooling/repo-kit; overwritten on every kit update. Standard: .agents/SESSIONS.md.
"""
import argparse, fnmatch, json, subprocess, sys
from pathlib import Path

def git(root, *args, check=True):
    return subprocess.run(["git", *args], cwd=root, check=check, text=True, capture_output=True).stdout

ROOT = Path(git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel").strip())
_pol = ROOT / ".agents/repository-policy.json"
POLICY = json.loads(_pol.read_text()) if _pol.exists() else {}
LIVE = {"planned", "active", "review-ready", "blocked"}

def match(path, pattern):
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.removeprefix("**/"))

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

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--path", action="append", default=[], help="limit --check to an owned path/prefix")
    p.add_argument("--against", help="also check paths this branch changed relative to REF (e.g. origin/main)")
    a = p.parse_args()
    if not (a.preflight or a.check): p.error("choose --preflight or --check")
    branch = git(ROOT, "branch", "--show-current").strip() or "(detached)"
    changed = [line[3:] for line in git(ROOT, "status", "--porcelain=v1", "--untracked-files=all").splitlines() if len(line) > 3]
    if a.against:
        changed = sorted(set(changed) | set(x for x in git(ROOT, "diff", "--name-only", f"{a.against}...HEAD", check=False).split("\n") if x))
    if a.path:
        changed = [x for x in changed if any(x == q.rstrip("/") or x.startswith(q.rstrip("/") + "/") for q in a.path)]
    errors, warnings = [], []
    linked = Path(git(ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent.resolve() != ROOT.resolve()
    if a.preflight:
        if changed: warnings.append(f"worktree has {len(changed)} changed paths; treat them as user-owned")
        if not linked: warnings.append("this is the primary checkout; start a session: python3 .agents/bin/session start <task>")
    if a.check:
        diff_args = ["git", "diff", "--check"] + (["--", *a.path] if a.path else [])
        dc = subprocess.run(diff_args, cwd=ROOT, text=True, capture_output=True)
        if dc.returncode: errors.append("git diff --check failed: " + dc.stdout.strip()[:600])
        for root in POLICY.get("external_read_only_roots", []):
            hits = [x for x in changed if x == root or x.startswith(root + "/")]
            if hits: errors.append(f"external read-only paths changed under {root}: {', '.join(hits[:8])}")
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
        if changed and not any(x.startswith(".agents/handoffs/") for x in changed):
            warnings.append("no task handoff is present in the change set")
        # Only an overlap involving this change's own task blocks; older overlaps are reported, not fatal.
        mine = {Path(x).stem for x in changed if x.startswith(".agents/tasks/") and x.endswith(".json")}
        active = [t for t in tasks() if t.get("status") in LIVE or t.get("id") in mine]
        for i, left in enumerate(active):
            for right in active[i + 1:]:
                for lp in left.get("owned_paths", []):
                    for rp in right.get("owned_paths", []):
                        if lp == rp or lp.startswith(rp.rstrip("/") + "/") or rp.startswith(lp.rstrip("/") + "/"):
                            msg = f"task ownership overlap: {left['id']} and {right['id']} at {lp} / {rp}"
                            (errors if (mine and {left.get('id'), right.get('id')} & mine) else warnings).append(msg)
    print(f"repository: {ROOT}\nbranch: {branch}\nchanged paths: {len(changed)}")
    for x in errors: print("ERROR:", x)
    for x in warnings: print("WARNING:", x)
    if not errors and not warnings: print("OK: no findings")
    return bool(errors)

if __name__ == "__main__": sys.exit(main())
