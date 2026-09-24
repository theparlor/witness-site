# Agent instructions

<!-- session-kit:begin (managed by org-design-tooling/repo-kit; edits inside are overwritten) -->
## Parallel sessions (branching standard)

This repo is trunk-based and runs one worktree per session. Never edit the primary checkout.
Start with `python3 .agents/bin/session start <task> --own <path>` and work in the worktree it
prints. See who else is working here with `python3 .agents/bin/session status`. When your
commits are in, run `python3 .agents/bin/session land`, then `python3 .agents/bin/session finish`.
A rebase conflict with another session is resolved by meaning, keeping both intents. Before any
push, `.agents/bin/portability-check` runs locally (pre-push hook and `session land`). The full
standard is `.agents/SESSIONS.md`; the installed kit version is in `.agents/KIT_VERSION`.
<!-- session-kit:end -->
