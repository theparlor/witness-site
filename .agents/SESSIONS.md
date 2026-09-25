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
runs the checks on the machine, and lands as one squashed commit on main.

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
6. **Land locally by default, as one squashed commit.** `session land` squashes the branch onto
   `origin/main` and pushes it as a fast-forward: no pull request and no pull-request CI run,
   because the checks already ran on the machine (WS-DDR-143 amendment 2026-09-24). It uses a
   pull request (squash merge, branch deleted on merge) only when the change touches an ask
   path (rule 7), when main has a ruleset or protection that requires a pull request or status
   checks, or when you pass `--pr`. A direct push GitHub refuses as protected falls back to a PR.
7. **Ship, show, ask.** Changes inside your owned paths ship: they land locally, or the PR
   merges when checks pass. Paths listed in `ask_paths` in `.agents/repository-policy.json`
   go through a PR that waits for a human.
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

Run inside your worktree once your work is committed. It closes your task file (folded into
your last commit when that commit has not been pushed yet, so there is no separate
`session: close` commit to pay CI for), rebases onto `origin/main`, runs the audit and the
portability check, then lands: by default as one squashed commit pushed straight to main
(retrying the rebase if another session landed in between), and through a PR where rule 6
says so, squash-merging it or leaving it open for a human when it touches an ask path.
`--pr` forces a PR; `--no-merge` opens one and leaves it. When the landing completes in line,
`land` also fast-forwards the primary checkout; when a PR's auto-merge is armed (checks still
running) the primary lags until `finish` runs or the hub's primary-ff sweep passes, and `land`
says so. If the rebase hits a conflict it stops and lists
the files: resolve them by meaning, `git add` them, `git rebase --continue`, run `land` again.

After a landing your branch points at the commit that landed it (same files, so nothing in the
worktree changes), and you can keep working in the same worktree and land again: the next `land`
replays only the new commits. A branch that still carries commits that already landed (a PR that
auto-merged after main moved, or a branch landed by a kit before version 12) has them skipped
before the rebase, and `land` says how many. Without that skip, the old commits were replayed onto
their own squash, and batches that touched the same lines conflicted with themselves under a
message that blamed another session. `finish` counts a merged PR as done only when it merged the
branch's current head.

A file your branch stops tracking (`git rm --cached`, usually with a `.gitignore` entry) stays on
disk through `land`. Without help it would not: the rebase checks out a main that still tracks the
file, git replaces an ignored file there without asking, and replaying your untrack commit then
deletes it. So before rebasing, `land` copies each such file into this worktree's git dir
(`session-kept/`, where no checkout, rebase or clean reaches) and puts it back afterwards. If a
conflict stops the rebase first, the copy waits there and the next `land` restores it. A copy is
never put over a file something has written since: `land` names both, and `finish` refuses to
remove the worktree, which would delete the kept copy, until you have merged them by hand and
deleted the kept one.

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

## Checks run on this machine, before the push

`.agents/bin/portability-check` is the check GitHub Actions used to run on every push: the
repo's own no-hardcoded-home test (`test_no_hardcoded_home.py` or `test-no-hardcoded-home.sh`,
wherever it is tracked; pytest is not needed) and a syntax check of every tracked `*.sh` and
`*.bash` by its shebang. Paths under `external_read_only_roots` and `portability_exclude` in
`.agents/repository-policy.json` are skipped. It runs in three places:

1. **Before every push**, as a git pre-push hook: `.agents/hooks/pre-push`, turned on per clone
   by `session start`, `session land` and the kit installer as a config hook
   (`hook.session-kit-portability.*`, git 2.54 or later). A config hook runs beside any pre-push
   hook the repo or a tool already has; it never replaces one. On an older git the kit writes a
   `.git/hooks/pre-push` shim, but only where no pre-push hook exists.
2. **In `session land`**, after the audit and before the push. A failure stops the land.
3. **In CI, as a backstop only.** Where the kit manages `.github/workflows/portability.yml`, it
   runs on pushes to main and on pull requests, only when a file the check reads changed, and a
   newer run on the same ref cancels the older one. A hand-customized workflow is left alone.

Fix a failure here; do not push around it.

## What the hooks enforce

A Claude Code hook blocks Write and Edit into the primary checkout of any repo that carries
this file. Another blocks `git worktree add` to anywhere but the sibling pattern (the desktop
app makes its worktrees outside that hook, which is why they are the second valid place). Both
print the command to run instead. A repo may add a commit-time backstop of its own (the Subaru
engagement's pre-commit does); it must admit both valid places.
