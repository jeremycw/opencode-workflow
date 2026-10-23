---
description: "Work the issue queue: status | next | all | accept <id> | reject <id>. Default is one numeric prefix group per invocation, claimed and committed before dispatch to one lead per issue in parallel worktrees, then finished only after all group leads report, and stopped at review for user acceptance."
agent: orchestrator
---

$ARGUMENTS

Interpret the arguments as one of:

- *empty* or `next` — find the current prefix group with
  `python3 scripts/issue_queue.py next-group`. If it prints `none`, check
  `python3 scripts/issue_queue.py list inprogress`: a non-empty list means the
  active group is fully claimed — report and wait, and never start a later
  prefix. If the remaining `inprogress` work is blocked/failed, ask the user to
  return/retry it (`return "<exact filename>"`); the active prefix keeps
  blocking later groups until it clears. Otherwise there is no claimable todo
  work (review/completed items may exist). When there is work, claim
  **every todo member of the group before dispatch**, using quoted exact
  filenames (`start "001 A.md"`), because a numeric id is ambiguous when
  siblings share a prefix. If a claim fails mid-group, dispatch nothing: return
  the just-claimed issues (if any) to `todo` with `return "<exact filename>"` —
  no work was dispatched — commit those issue-state moves (if any), and report.
  If all claims succeed, commit only the claim moves (`git add issues && git
  commit -m "issues: claim group <prefix>" -- issues`) **before** dispatching;
  stage only the moved state files (never `issues/README.md`) and confirm with
  `git diff --cached --name-only`. This keeps main clean of issue moves for
  `worktree_apply` (it refuses a dirty main). Then check
  `git status --porcelain`: if unrelated uncommitted/untracked changes remain,
  do not dispatch; return the just-claimed issues to `todo`, commit those moves
  (if any), report the dirty checkout as blocked, and never commit user work.
  Then dispatch one `lead` subagent per claimed issue **in parallel** (multiple
  task calls in one message). Instruct each lead to use a worktree
  (`worktree_create` with a unique branch, do the full loop inside it, commit
  there, then `worktree_apply` with merge): clean apply -> re-run tests on main
  and `worktree_delete`; in-scope conflicts -> resolve/stage/commit in main,
  re-run tests, delete; out-of-scope conflict or failed merge -> if the failed
  apply actually left a merge in progress, abort that merge, otherwise do not
  call abort (wait/retry or report); never abort a merge you did not start;
  keep the worktree, report `blocked` and how main was left. Leads never push,
  never edit or move `issues/`, and never mark an issue complete.
  Collect **all** group lead reports before changing queue state: do not
  `finish` anything while a lead may still be applying a merge. Then run
  `python3 scripts/issue_queue.py finish "<exact filename>"` for each success
  into `review`, leave `blocked`/`failed` issues in `inprogress`, report the
  blockers, and commit the resulting issue-state moves in one `issues:` commit.
- `status` — run `python3 scripts/issue_queue.py status` and report the queue
  (todo / inprogress / review / completed). Do not mutate anything.
- `all` — process prefix groups sequentially in numeric order using the same
  claim-the-whole-group-before-dispatch loop. Within one group, dispatch one
  `lead` per issue in parallel worktrees and collect every report before
  finishing any member. A group is **not finished while any member remains
  `inprogress`**: successes move to `review`, while blocked/failed members stay
  `inprogress` and are reported, so the active prefix keeps blocking later
  groups. Do not start the next group until the user returns/retries (or
  abandons via `return`) the blocked/failed members. Every issue still stops at
  `review`; never auto-accept and never skip the acceptance gate.
- `accept <id>` — the user has accepted a `review` issue; run
  `python3 scripts/issue_queue.py complete <id>`. When a prefix is shared,
  use the exact filename; if it is ambiguous, list the `review` filenames and
  ask the user which one to accept.
- `reject <id>` — return a `review` issue to `todo` with
  `python3 scripts/issue_queue.py reopen <id>` and report why. Use the exact
  filename when a prefix is shared; if ambiguous, list the `review` filenames
  and ask the user which one to reject.

One prefix group per invocation by default (normally one issue). Never
implement, plan, or edit project files yourself. Use
`python3 scripts/issue_queue.py` for every state change; do not move issue
files by hand. Commit only issue-state moves (`git add issues && git commit -m
"issues: ..." -- issues`). Never push, and never mark an issue complete
without explicit user acceptance.
