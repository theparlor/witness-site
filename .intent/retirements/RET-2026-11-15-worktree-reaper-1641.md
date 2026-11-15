---
title: Worktree reaper pass 2026-11-15 16:41
type: retirement-manifest
maturity: final
created: 2026-11-15
---

# Worktree reaper pass, 2026-11-15 16:41

The hourly worktree reaper (org-design-tooling `repo-kit/worktree_reaper.py`, LaunchAgent com.brien.worktree-reaper) retired these linked worktrees of this repo. Each one's work was already on main, nothing had touched it within the idle window, and no running process or recent Claude session was using it. Nothing was lost: each tip is pinned by a pushed archive tag, and each uncommitted file was kept as listed. The worktree folder and its local branch were removed after this record landed.

## witness-site-wt-2026-11-14-kit38-reaper-probe

- Path: `~/Workspaces/Core/products/witness-site-wt-2026-11-14-kit38-reaper-probe` (kit worktree)
- Branch: `agent/claude/2026-11-14-kit38-reaper-probe`, tip `8f489717`, last commit 2026-11-14
- Tag: `archive/agent/claude/2026-11-14-kit38-reaper-probe-2026-11-15`
- Landing on main: tip is on origin/main
- Idle: 24.3 hours when retired
- Residue: 2 uncommitted session record(s) or hook log(s) landed in .agents/residue/witness-site-wt-2026-11-14-kit38-reaper-probe/
- Commits not on main by hash: none
- Files those commits touched: none
- Recover: `git checkout -b agent/claude/2026-11-14-kit38-reaper-probe archive/agent/claude/2026-11-14-kit38-reaper-probe-2026-11-15`
