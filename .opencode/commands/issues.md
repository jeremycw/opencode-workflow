---
description: "Work the issue queue: status | next | all | accept <id> | reject <id>. Default is one numeric prefix group per invocation, claimed and committed before dispatch to one lead per issue in parallel worktrees, then finished only after all group leads report, and stopped at review for user acceptance. On explicit accept the orchestrator merges the canonical branch and, on conflicts, dispatches a fresh lead acceptance conflict resolver in the main checkout, verifies the merge, then completes."
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
  work (review/completed items may exist). Before claiming, resolve every
  group member's canonical branch read-only with
  `python3 scripts/issue_queue.py branch "<exact filename>"`; if any lookup
  fails (unknown, ambiguous, or duplicate branch), dispatch nothing and report.
  If `python3 scripts/issue_queue.py list review` is non-empty, warn (do NOT
  block) that those review branches are still unmerged and merge only on user
  acceptance. When there is work, claim **every todo member of the group before
  dispatch**, using quoted exact filenames (`start "001 A.md"`), because a
  numeric id is ambiguous when siblings share a prefix. If a claim fails
  mid-group, dispatch nothing: return the just-claimed issues (if any) to
  `todo` with `return "<exact filename>"` — no work was dispatched — commit
  those issue-state moves (if any), and report. If all claims succeed, commit
  only the claim moves (`git add issues && git commit -m "issues: claim group
  <prefix>" -- issues`) **before** dispatching; stage only the moved state
  files (never `issues/README.md`) and confirm with `git diff --cached
  --name-only`. This keeps main clean of issue moves for `worktree_apply` (it
  refuses a dirty main). Then check `git status --porcelain`: if unrelated
  uncommitted/untracked changes remain, do not dispatch; return the just-claimed
  issues to `todo`, commit those moves (if any), report the dirty checkout as
  blocked, and never commit user work. Then dispatch one `lead` subagent per
  claimed issue **in parallel** (multiple task calls in one message), passing
  each issue's canonical branch explicitly. Instruct each lead to
  `worktree_create(branch: "<canonical>", baseBranch: "main")`. Before
  creating anything, the lead must run
  `git rev-parse --verify --quiet refs/heads/<canonical>` AND inspect
  `worktree_list` for that branch; if either exists, it reports `Outcome:
  blocked` and does not create, reuse, or delete anything. The lead does the
  full loop **inside** that worktree and commits/runs
  tests there; it does NOT `worktree_apply`, does NOT merge into the default
  branch (`main` here; `master` where that is the default), and does NOT
  delete the worktree — it leaves branch and worktree intact for acceptance.
  On blocked/failed both stay intact. Each lead reports `Outcome`, issue id,
  branch, worktree path, and head SHA, never pushes, never edits or moves
  `issues/`, and never marks an issue complete. Collect **all** group lead
  reports before changing queue state. Then for each success compute its branch
  with `python3 scripts/issue_queue.py branch "<exact filename>"`, require a
  non-empty name, verify `git rev-parse --verify --quiet refs/heads/<branch>`,
  and require at least one commit beyond the default branch:
  `git rev-list --count refs/heads/main..refs/heads/<branch>` (`master` where
  that is the default) must be greater than 0 — a zero-commit branch is
  blocked even when the default branch has advanced since creation.
  Missing/empty branch or a failed check leaves that issue `inprogress` and is
  reported. Do NOT merge and do NOT delete the worktree at finish. Run
  `python3 scripts/issue_queue.py finish "<exact filename>"` only for verified
  successes into `review`, leave `blocked`/`failed` issues in `inprogress`,
  report the blockers, and commit only the resulting issue-state moves in one
  `issues:` commit.
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
- `accept <id>` — the user has accepted a `review` issue. This is the only
  merge path and it runs only on explicit user acceptance. Compute its branch
  with `python3 scripts/issue_queue.py branch "<exact filename>"` (exact
  filename when a prefix is shared; if ambiguous, list the `review` filenames
  and ask the user which one). Verify the main checkout is on the default
  branch (`main` here; `master` where that is the default) and that the branch
  exists (`git rev-parse --verify --quiet refs/heads/<branch>`); otherwise keep
  it in `review` and report blocked. Record `PRE_MERGE=$(git rev-parse HEAD)`.
  Probe `MERGE_HEAD` FIRST, before the clean-status gate: a crashed acceptance
  merge leaves unmerged paths, so `git status --porcelain` is dirty and a
  clean-status check would make recovery unreachable. If `MERGE_HEAD` exists:
  - if `git rev-parse MERGE_HEAD` equals
    `git rev-parse refs/heads/<branch>` (provably this branch's crashed
    acceptance merge), abort it with
    `worktree_resolve_conflicts(strategy: "abort")`, then confirm `MERGE_HEAD`
    is gone and `git status --porcelain` is clean and report blocked so the
    user can retry accept; if the abort or that confirmation fails, do NOT
    reset/clean and report failed with the exact state;
  - otherwise report blocked and do NOT abort a merge this invocation did not
    start.
  Only when no `MERGE_HEAD` exists, require clean `git status --porcelain`;
  otherwise keep it in `review` and report blocked. Then
  `worktree_apply(branch, mode: "merge")` on clean main.
  - Hard error with no conflicts: keep the issue in `review`. Abort only a
    merge this invocation started, and only while provenance holds —
    `MERGE_HEAD` exists, `git rev-parse MERGE_HEAD` equals the canonical branch
    tip, and `HEAD` equals `PRE_MERGE` — with
    `worktree_resolve_conflicts(strategy: "abort")`; otherwise do not abort.
    Report blocked; never reset.
  - Clean merge: require `git merge-base --is-ancestor refs/heads/<branch>
    HEAD` and clean `git status --porcelain`. If either check fails, keep the
    issue in `review`, report blocked, and never reset/delete/complete (do not
    run the suites or complete). Otherwise run BOTH suites on main
    (`python3 -m unittest discover -s tests` and
    `python3 -m unittest discover -s sandbox`). Green ->
    `python3 scripts/issue_queue.py complete "<exact filename>"`, commit only
    the queue move, then `worktree_delete(branch, deleteBranch: "auto")` (the
    merged branch is deleted). Red -> keep `review`, report blocked, do NOT
    reset or delete (main is already merged). Do not require `HEAD^2` on a
    clean/fast-forward merge.
  - Conflicts: do NOT abort. Confirm `MERGE_HEAD` exists and
    `git diff --name-only --diff-filter=U` is non-empty; capture the
    conflicted file list. Dispatch exactly one fresh `lead` labelled
    "acceptance conflict resolver", working in the MAIN checkout (not a
    worktree), passing the exact issue filename (read-only), the canonical
    branch, the conflicted files, and `PRE_MERGE`. This is the ONLY dispatch
    allowed while main is mid-merge (it is your own acceptance merge, not
    unrelated WIP); do no other queue or `/ship` work while the resolver holds
    main (one acceptance at a time). Never edit or resolve conflicts yourself
    (you have `edit` denied).
    - Resolver success: independently gate on no `MERGE_HEAD`; HEAD is a merge
      commit (`git rev-parse --verify --quiet HEAD^2`); the canonical branch is
      an ancestor of HEAD (`git merge-base --is-ancestor`); clean
      `git status --porcelain`; on the default branch; then re-run BOTH suites.
      All pass -> `complete`, queue-only commit,
      `worktree_delete(branch, deleteBranch: "auto")`. Any failure -> keep the
      issue in `review`, keep the worktree/branch, report blocked, and never
      reset/delete/complete.
    - Resolver blocked/failed/missing report: abort only while the acceptance
      merge this invocation started is provably still in progress — `MERGE_HEAD`
      exists AND `git rev-parse MERGE_HEAD` equals the canonical branch tip AND
      `HEAD` equals `PRE_MERGE`. The one-acceptance-at-a-time rule plus this
      provenance check protects a live merge.
      - If provenance fails (or no `MERGE_HEAD` exists, for example the
        resolver already committed), do NOT abort; report failed with the
        exact state.
      - If provenance holds, abort with
        `worktree_resolve_conflicts(strategy: "abort")`, then verify
        `MERGE_HEAD` is gone, `git status --porcelain` is clean, and `HEAD`
        equals `PRE_MERGE`. If that restoration check passes, report blocked,
        keep the issue in `review`, and keep the worktree/branch intact. If the
        abort or that restoration check fails, report failed with the exact
        state.
      In all cases never reset/clean/delete.
  A deletion failure after completion is non-fatal and reported.
- `reject <id>` — reject a `review` issue. Resolve its branch, then clean up
  BEFORE the state move with `worktree_delete(branch, deleteBranch: "always",
  commitPending: false)` to discard abandoned WIP. If the tool says no
  worktree was found, probe the branch with `git rev-parse --verify --quiet
  refs/heads/<branch>`: absent -> proceed; present -> orphan branch, report
  blocked and leave state unchanged. Any other cleanup failure -> blocked and
  state unchanged. Then `python3 scripts/issue_queue.py reopen "<exact
  filename>"` and commit the queue move; report why. `return` uses the same
  cleanup-before-move path before `python3 scripts/issue_queue.py return
  "<exact filename>"`. Use the exact filename when a prefix is shared; if
  ambiguous, list the `review` filenames and ask the user which one to reject.

One prefix group per invocation by default (normally one issue). Never
implement, plan, review, or edit project files yourself; use only queue moves,
worktree tools, git checks, test commands, and queue-state commits. Use
`python3 scripts/issue_queue.py` for every state change; do not move issue
files by hand. Commit only issue-state moves (`git add issues && git commit -m
"issues: ..." -- issues`). Never push, and never mark an issue complete
without explicit user acceptance.
