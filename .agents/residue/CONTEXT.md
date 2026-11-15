---
title: Worktree residue
type: reference
maturity: living
created: 2026-11-15
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
