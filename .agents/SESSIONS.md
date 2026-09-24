---
title: Sessions and branching in this repo
type: standard
maturity: ratified
created: 2026-09-23
managed_by: org-design-tooling/repo-kit (this file is overwritten on every kit update; put repo-specific rules in .agents/WORKFLOW.md)
authority: WS-DDR-131 in theparlor/workspaces-governance, ratified 2026-09-23
---

# Sessions and branching in this repo

## Why this exists

Two sessions can work on this repo at the same time, on two different questions, and both
can land. That only works when neither session writes to the shared checkout. Each one works
in its own copy (a git worktree) on its own short-lived branch. When a session is done, it
rebases onto whatever main now holds, including anything the other session already landed,
and merges through a pull request.

## The rules

1. **Main is the only long-lived branch.** The primary checkout stays on main. Nobody edits
   it, human or agent. It only ever moves forward by `git pull --ff-only`.
2. **One session, one worktree, one branch.** A session worktree lives in one of two places
   and nowhere else. A worktree the kit makes (`session start <task>`) is a sibling of the
   primary checkout named `<repo>-wt-<task>`, on branch `agent/<provider>/<yyyy-mm-dd>-<task>`,
   cut from `origin/main`. A worktree the Claude desktop app makes when a session opens from
   the repo's own folder lives at `<repo>/.claude/worktrees/<name>`, on the app's branch name;
   it is already isolated and gitignored, and it is the worktree that session uses. Inside it,
   `session start <task> --here` writes the task file and handoff of rule 3 without cutting a
   second worktree. A worktree anywhere else (a session scratchpad, `/tmp`, a copy outside the
   repo's folder) is not a session worktree and the hooks refuse it. A gate that refuses one of
   the two valid places is wrong; correct the gate, never move the work to satisfy it.
3. **Say what you own.** `session start` writes a task file under `.agents/tasks/` and a
   handoff under `.agents/handoffs/`. Name the paths you expect to change with `--own`.
   Overlap between two live sessions shows up in `session status` before either lands.
4. **Land small and the same day.** A branch lives for one unit of work. Anything that
   cannot land the day it starts is scoped too big: split it.
5. **Settling two sessions.** Whoever lands second rebases onto the first one's result.
   A conflict is analysis work, not a text merge: read what both sessions meant, keep both
   intents, then continue. Never discard the other session's change to make yours apply.
6. **Squash merge through a PR, branch deleted on merge.** The repo only allows squash
   merges and deletes the branch when the PR merges.
7. **Ship, show, ask.** Changes inside your owned paths ship: the PR merges when checks
   pass. Paths listed in `ask_paths` in `.agents/repository-policy.json` wait for a human.
8. **Regenerable output is not committed from a working branch.** If a pipeline can rebuild
   it, it is gitignored or landed by that pipeline's own snapshot step.
9. **Never destroy another session's work.** No `reset --hard`, no `clean`, no stash of
   changes you did not make, no worktree removal while it has uncommitted changes.

## The commands

Run from anywhere inside the repo: the primary checkout or any worktree.

```bash
python3 .agents/bin/session start <task> --own <path> --objective "<one line>"
```

Creates the worktree and branch and prints the worktree path. Do all your work there.

```bash
python3 .agents/bin/session status
```

Lists every live session on this repo: its branch, what it has changed, how far behind main
it is, and any file two sessions both touch. It also prints how far behind `origin/main` the
primary checkout is (`primary: N behind`), so a landed change that has not reached the shared
checkout is visible before anyone opens a stale file from it.

```bash
python3 .agents/bin/session land
```

Run inside your worktree once your work is committed. It closes your task file, rebases onto
`origin/main`, runs the audit, pushes, opens the PR and squash-merges it, or leaves it open
for a human when it touches an ask path. When the merge completes in line, `land` also
fast-forwards the primary checkout; when auto-merge is armed (checks still running) the
primary lags until `finish` runs or the hub's primary-ff sweep passes, and `land` says so. If the rebase hits a conflict it stops and lists
the files: resolve them by meaning, `git add` them, `git rebase --continue`, run `land` again.

```bash
python3 .agents/bin/session finish
```

After the merge: fast-forwards the primary checkout, removes your worktree (only if it is
clean) and deletes the local branch.

```bash
python3 .agents/bin/agent_repo_audit.py --check
```

Read-only checks: read-only roots untouched, generated output has its source, no session
scratch paths in code, no two live tasks own the same path.

## What the hooks enforce

A Claude Code hook blocks Write and Edit into the primary checkout of any repo that carries
this file. Another blocks `git worktree add` to anywhere but the sibling pattern (the desktop
app makes its worktrees outside that hook, which is why they are the second valid place). Both
print the command to run instead. A repo may add a commit-time backstop of its own (the Subaru
engagement's pre-commit does); it must admit both valid places.
