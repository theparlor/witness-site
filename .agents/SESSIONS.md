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

Run from inside the repo: the primary checkout or any of its worktrees. The repo is the one the script
lives in (the parent of `.agents/`), never merely the one the shell is standing in. A shell in a
different repository gets one line naming both, exit status 2, and nothing changes: `cd` into the repo
and run it again, or pass `--here` to act on the repository the shell is in (`start --here` also adopts
the worktree, rule 2). A shell in no repository uses the script's own. Each run reports one event to
Witness when Witness is on the machine (WS-DDR-150); a missing or failing Witness changes nothing.

```bash
python3 .agents/bin/session start <task> --own <path> --objective "<one line>"
```

Creates the worktree and branch and prints the worktree path. Do all your work there. It first
checks free disk, and refuses when the new checkout would leave too little (kit 21, below).

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
`session: close` commit to pay CI for), rebases onto `origin/main`, runs the audit, the
repository's own pre-land commands (if it declares any) and the portability check, then lands:
by default as one squashed commit pushed straight to main
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

Read-only checks: read-only roots untouched (a byte-identical move that stays inside the root, a
deletion whose bytes remain at another path under it, and an index file such as CONTEXT.md at any
depth are not edits of an original; kit v16), generated output has its source, no session
scratch paths in code, no two live tasks own the same path.

## Checks run on this machine, before the push

`.agents/bin/portability-check` is the check GitHub Actions used to run on every push: the
repo's own no-hardcoded-home test (`test_no_hardcoded_home.py` or `test-no-hardcoded-home.sh`,
wherever it is tracked; pytest is not needed; module-level `test_*` functions and
`unittest.TestCase` classes both run, and a file that runs no test fails) and a syntax check
of every tracked `*.sh` and `*.bash` by its shebang. Paths under `external_read_only_roots` and `portability_exclude` in
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

### The repository's own pre-land commands (kit 18)

A repository can name commands that must pass before anything reaches its main branch: a list
under `pre_land` in `.agents/repository-policy.json`, each entry
`{"name": "...", "run": ["{python}", "path/to/check.py"], "timeout_s": 300}`. `{python}` is the
interpreter running `session`; a relative path is relative to the worktree. `session land` runs
them in the session worktree, in order, on the tree that would land: after the rebase onto
`origin/main` and the audit, before the portability check and the push, and again whenever
another session lands first and the land rebases a second time. A command that exits non-zero,
or outlives its timeout (it is killed with its whole process group), stops the land with exit
status 1: nothing is pushed, and the branch and the worktree stay as they were. The last 40
lines of its output are shown either way. A policy file that does not parse, or an entry with
no name, no `run` list or a timeout outside 1 to 1800 seconds, stops the land too, so a broken
declaration never turns the gate off without a word. The default is none (`"pre_land": []`).

Keep them fast and local: they run on every land of every session. Cast's is its
`gate`-marked tests (`engine/scripts/gate_tests.py`, under a minute, no model call, no
network), added after a test encoding a pipeline invariant stayed red on every branch for
four days in September 2026.

### A land never reverts another session's landing (kit 19)

Every worktree of a repository shares `refs/remotes/origin/main`, and each session's `git push`
moves it. Through kit 18, `land` rebased onto `origin/main`, ran its checks (about a minute with
a pre-land gate), then built the squash with `origin/main` read again as its parent. When a
sibling session landed in that minute, its landing became the parent while the tree was still
the older base plus this branch: the push was a fast-forward, the retry never ran, and main lost
the sibling's files (Cast e2bcc5811, 466d01305, 51487a026 and 7f6dfcbaf, 30 September 2026).

Now `land` reads `origin/main` once, rebases onto that commit and builds the squash on that
same commit. If main moved meanwhile, the push is refused as non-fast-forward and the land
fetches, rebases and runs the checks again. A guard also refuses, before the push, any squash
that changes a path none of the branch's own commits touched: that can only be another
session's landing being undone. Nothing is pushed; land again.

### Reading another session's worktree never takes its lock (kit 20)

`session status` reads every live session's worktree, and `session start` does the same to list
them. A plain `git status` refreshes the index as a side effect: it takes that worktree's
`index.lock` and holds it while it walks the worktree. Through kit 19, the session that owned the
worktree could have its own `git add` fail in that moment ("index.lock: File exists"); a land
that did not check its add committed half of its files (Cast, 30 September 2026).

Now every read the kit makes of a worktree runs with `GIT_OPTIONAL_LOCKS=0`. Git then skips the
optional refresh and takes no lock; what the read reports is the same. The kit's own writes
(fetch, rebase, commit, the primary's fast-forward) take their locks as before. A script of your
own that inspects another session's worktree should do the same:
`GIT_OPTIONAL_LOCKS=0 git -C <worktree> status`.

### Free disk before a new worktree (kit 21)

Every session worktree is a full checkout: 0.65 to 3.5 GB each across these repos. On 2 October
2026 about 105 of them had piled up on one machine, the disk fell to 2 GB free, and nothing had
said a word as each one was cut.

Now `start` measures the disk that will hold the new worktree before `git worktree add`, and
estimates the checkout from the sizes git records for the base tree (`git ls-tree -r -l`, under a
second even for the largest repo; it never walks the primary). Then:

- If the checkout would leave less than 10 GB free, `start` refuses: exit status 1, no worktree,
  no branch, no task file. The message gives the free space, the estimate, the floor and how many
  worktrees this repo already has, and says what to do: `session status` to see them, `session
  finish` in each one that has landed. The hourly worktree reaper (`com.brien.worktree-reaper`)
  retires landed, idle worktrees on its own.
- If it would leave less than 25 GB, `start` goes ahead and prints a line beginning
  `session: WARNING: LOW DISK` on stderr.
- `start --here` checks nothing out, so it only ever warns.
- Anything that goes wrong while measuring prints one note and the start goes ahead unguarded.

`SESSION_MIN_FREE_GB` and `SESSION_WARN_FREE_GB` move the two lines. `SESSION_ALLOW_LOW_DISK=1`
starts anyway, for that one command. The Witness event of a `start` carries the numbers
(`free_gb`, `estimate_gb`) and the result (`disk_guard`: `guard_ok`, `guard_warn`,
`guard_refused`, `guard_overridden`, or `guard_skipped` when measuring failed); a refusal is
reported as `blocked` with reason `low_disk`.

## What the hooks enforce

A Claude Code hook blocks Write and Edit into the primary checkout of any repo that carries
this file. Another blocks `git worktree add` to anywhere but the sibling pattern (the desktop
app makes its worktrees outside that hook, which is why they are the second valid place). Both
print the command to run instead. A repo may add a commit-time backstop of its own (the Subaru
engagement's pre-commit does); it must admit both valid places.
