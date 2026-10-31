# Agent handoff: name-purge-record

- Status: complete
- Provider/agent: claude
- Objective: record the 2026-10-31 name purge of this public repo's history: manifest, ledger row, KF-11 review in the handoff
- Worktree and branch: `../witness-site-wt-2026-10-31-name-purge-record`, `agent/claude/2026-10-31-name-purge-record`
- Base and head commits: base `43b9eb7`; head recorded at merge.
- Owned paths: `.intent/retirements`, `.agents/handoffs`
- Changed paths:
- Canonical inputs:
- Generated outputs:
- External reads:
- External writes: none (the force-push and the PR merges were done before this session, by purge-one.sh and merge-prs.sh; see the manifest)
- Checks and results:
- Decisions made:
- Unresolved risks or decisions:
- Safest next action:

<!-- kf11:start -->
## KF-11 review: a content change over the threshold

This landing is one of 16 (the public theparlor site repos), 2 kit files each, 32 kit files in all plus
one manifest and one ledger row per repo. Rule KF-11 (any content change over 25 files, counted per
session and per day, lands only as a reviewed diff with the reviewer's yes in the description): the work
is not split to stay under the count.

**The reviewer's yes.** Brien, 2026-10-31, in reply to a message naming exactly these two kit comments in
all 16 public site repos: "address without permanently losing data".

| File | Change |
|---|---|
| `.agents/bin/agent_repo_audit.py` | kit file; 17 history line(s) across the seven kit substrings reworded by the rewrite (tip already public from PR) |
| `.agents/bin/retirement.py` | kit file; 17 history line(s) across the seven kit substrings reworded by the rewrite (tip already public from PR) |
| `.intent/retirements/RET-2026-10-31-name-purge.md` | added: the manifest (bundle, sha256, old and new main, recover command) |
| `.intent/retirements/LEDGER.md` | one row appended (file created with the kit's header where it was absent) |

Old main 4c3c4796a609, new main e30eab1ec5dc. Bundle `witness-site-pre-name-purge-2026-10-31.bundle`, sha256 `8eb7c56e3eca7813c361b7a2c4279972690e53e76b17b99b5fcda77f1ac46745`.
Full record: `.intent/retirements/RET-2026-10-31-name-purge.md`.
<!-- kf11:end -->
