---
title: Worktree retirement 2026-10-31 04:52
type: retirement-manifest
maturity: final
created: 2026-10-31
---

# Worktree retirement, 2026-10-31 04:52

These worktrees were retired with their work NOT on main: abandoned, superseded, or a robot's run that a later run replaced (session kit `retire`, kit 29). Nothing was lost: everything uncommitted was folded into a snapshot commit, the tip is pinned by an archive tag, and the recover command below brings the branch back. The worktree folder and its local branch were removed after this record landed.

## witness-site-wt-2026-10-31-public-render

- Path: `~/Workspaces/Core/products/witness-site-wt-2026-10-31-public-render` (kit worktree)
- Branch: `agent/claude/2026-10-31-public-render`, tip `e30eab1e`, last commit 2026-10-26
- Tag: `archive/agent/claude/2026-10-31-public-render-2026-10-31`
- Landing on main: not on main
- Why retired: leftover of the 2026-10-31 public-render session: its one commit landed as the merged public-render PR, then the name purge rewrote history; nothing beyond main
- Residue: nothing uncommitted
- Commits not on main by hash: none
- Files those commits touched: none
- Recover: `git checkout -b agent/claude/2026-10-31-public-render archive/agent/claude/2026-10-31-public-render-2026-10-31`
