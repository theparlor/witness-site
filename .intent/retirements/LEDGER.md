---
title: Retirement ledger
type: reference
maturity: living
created: 2026-10-31
---
# Retirement ledger

Every branch, stash, or worktree deliberately discarded from this repo, with a pointer to the tag that still holds it
and a manifest of what it contained. Nothing listed here is gone: recover any row with the command in its manifest.
Grep this directory before concluding that anything was lost.

| Retired | Name | Kind | Holds it | Tip | Last real commit | Unique commits | Files | Why | Manifest |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-31 | witness-site-wt-2026-10-31-public-render | worktree | tag `archive/agent/claude/2026-10-31-public-render-2026-10-31` | e30eab1e | 2026-10-26 | 0 | 0 | Retired, work not on main: leftover of the 2026-10-31 public-render session: its one commit landed as the merged public-render PR, then the name purge rewrote history; nothing beyond main. | [RET-2026-10-31-session-retire-0452.md](RET-2026-10-31-session-retire-0452.md) |
| 2026-10-31 | pre-purge history (two client names in vendored kit comments) | history-rewrite | bundle `witness-site-pre-name-purge-2026-10-31.bundle` in ~/.local/state/retired-history-bundles/ (sha256 8eb7c56e3eca, verified) + local tag `archive/pre-name-purge-2026-10-31` (never pushed) | 4c3c479 | 2026-10-31 | 57 commits rewritten to 55 | 17 kit lines | Two kit provenance comments named a client in this public repo (guard Check 33, 2026-10-31); purged at egress on Brien's 2026-10-31 instruction "address without permanently losing data", bundle first; new main e30eab1 | [RET-2026-10-31-name-purge.md](RET-2026-10-31-name-purge.md) |
