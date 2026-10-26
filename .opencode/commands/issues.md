---
description: "Work the issue queue: status | next | all | accept <id> | reject <id>. Default is one numeric prefix group per invocation, claimed locally before dispatch to one lead per issue in parallel worktrees, then finished only after all group leads report, and stopped at review for user acceptance. Queue moves are local and create no git commits. On explicit accept the orchestrator stages one squash commit in a temporary accept/<id>-<slug> worktree (resolving conflicts there through one fresh lead), verifies it, fast-forwards main, restores the queue, completes locally, and deletes both worktrees/branches."
agent: orchestrator
---

$ARGUMENTS

Interpret the arguments as one of:

- *empty* or `next` — find the current prefix group with
  `python3 .opencode/scripts/issue_queue.py next-group`. If it prints `none`, check
  `python3 .opencode/scripts/issue_queue.py list inprogress`: a non-empty list means the
  active group is fully claimed — report and wait, and never start a later
  prefix. If the remaining `inprogress` work is blocked/failed, ask the user to
  return/retry it (`return "<exact filename>"`); the active prefix keeps
  blocking later groups until it clears. Otherwise there is no claimable todo
  work (review/completed items may exist). Before claiming, resolve every
  group member's canonical branch read-only with
  `python3 .opencode/scripts/issue_queue.py branch "<exact filename>"`; if any lookup
  fails (unknown, ambiguous, or duplicate branch), dispatch nothing and report.
  If `python3 .opencode/scripts/issue_queue.py list review` is non-empty, warn (do NOT
  block) that those review branches are still unintegrated and are integrated
  only on user acceptance. When there is work, claim **every todo member of the
  group before dispatch**, using quoted exact filenames (`start "001 A.md"`),
  because a numeric id is ambiguous when siblings share a prefix. If a claim
  fails mid-group, dispatch nothing: return the just-claimed issues (if any) to
  `todo` with `return "<exact filename>"` — no work was dispatched — and
  report. These are local moves with **no git commits**. Then check
  `git status --porcelain`: if unrelated uncommitted/untracked changes remain,
  do not dispatch; return the just-claimed issues to `todo`, report the dirty
  checkout as blocked, and never commit user work. This WIP check is about
  dispatch safety, not about committing queue moves. Then dispatch one `lead`
  subagent per claimed issue **in parallel** (multiple task calls in one
  message), passing each issue's canonical branch and the main checkout's issue
  path explicitly. Instruct each lead to
  `worktree_create(branch: "<canonical>", baseBranch: "main")`. Before
  creating anything, the lead must run
  `git rev-parse --verify --quiet refs/heads/<canonical>` AND inspect
  `worktree_list` for that branch; if either exists, it reports `Outcome:
  blocked` and does not create, reuse, or delete anything. The lead does the
  full loop **inside** that worktree and commits/runs tests there; it does NOT
  merge into the default branch (`main` here; `master` where that is the
  default), and does NOT delete the worktree — it leaves branch and worktree
  intact for acceptance. On blocked/failed both stay intact. Each lead reports
  `Outcome`, issue id, branch, worktree path, and head SHA, never pushes, never
  edits or moves `issues/`, never creates or commits queue files, and never
  marks an issue complete. Collect **all** group lead reports before changing
  queue state. Then for each success compute its branch with
  `python3 .opencode/scripts/issue_queue.py branch "<exact filename>"`, require a
  non-empty name, verify `git rev-parse --verify --quiet refs/heads/<branch>`,
  and require at least one commit beyond the default branch:
  `git rev-list --count refs/heads/main..refs/heads/<branch>` (`master` where
  that is the default) must be greater than 0 — a zero-commit branch is
  blocked even when the default branch has advanced since creation.
  Missing/empty branch or a failed check leaves that issue `inprogress` and is
  reported. Do NOT merge and do NOT delete the worktree at finish. Run
  `python3 .opencode/scripts/issue_queue.py finish "<exact filename>"` only for verified
  successes into `review`, leave `blocked`/`failed` issues in `inprogress`, and
  report the blockers. These are local moves with **no commit**.
- `status` — run `python3 .opencode/scripts/issue_queue.py status` and report the queue
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
  integration path, it runs only on explicit user acceptance, and it runs one
  acceptance at a time. Compute its branch with
  `python3 .opencode/scripts/issue_queue.py branch "<exact filename>"` (exact filename
  when a prefix is shared; if ambiguous, list the `review` filenames and ask
  the user which one). **Preflight** the main checkout: on the default branch (`main` here;
  `master` where that is the default), **clean outside `issues/` while the
  queue is still tracked (one-time migration)**, and no merge in progress. Run
  `git status --porcelain`: while `git ls-files issues` is non-empty (the
  one-time migration only), dirty paths under `issues/` are allowed (the local
  move's deleted tracked path plus untracked new path) and must not be staged
  or committed; every dirty path outside `issues/` blocks. After the migration
  `issues/` is ignored and this exception disappears naturally. Also require the
  branch exists (`git rev-parse --verify --quiet refs/heads/<branch>`) and no
  pre-existing `accept/<id>-<slug>` branch or worktree
  (`git rev-parse --verify --quiet refs/heads/accept/<id>-<slug>` and
  `worktree_list`). If an acceptance branch/worktree already exists, block; do
  not reuse or delete it. Any preflight failure keeps the issue in `review`
  and is reported blocked.
  For the one-time bootstrap, perform the local `finish` move first as a plain
  filesystem rename (never stage it, use `git mv`, or commit it). Record
  `PRE_MERGE=$(git rev-parse HEAD)` and snapshot the live queue by copying
  `issues/` to a temporary directory outside the repo **after** the local
  finish move, so the snapshot contains the review state. The snapshot is
  required for the one-time migration and harmless afterwards. Create a
  **temporary acceptance worktree** from the default branch:
  `worktree_create(branch: "accept/<id>-<slug>", baseBranch: "main")`
  (`master` where that is the default). In that worktree run
  `git merge --squash issue/<id>-<slug>` and create exactly **one** commit,
  message `issue <id>: <title>`. In the new-prompt bootstrap this applies the
  migration deletion cleanly because main HEAD still has the old tracked queue
  path; an already-committed finish uses the committed-finish fallback below.
  - **Conflicts:** do NOT resolve them yourself and do NOT touch the main
    checkout. Confirm `git diff --name-only --diff-filter=U` is non-empty,
    capture the conflicted file list, and dispatch exactly one fresh `lead`
    labelled "acceptance conflict resolver" to work **only in the temporary
    acceptance worktree** — never the main checkout and never by merging there.
    Pass the worktree path, the main checkout's issue path (read-only), the
    canonical branch, the conflicted files, and `PRE_MERGE`. The resolver
    preserves both sides' intent, stages resolutions, runs both suites, gets
    independent `reviewer` approval, and creates the single squash commit with
    `git commit -m "issue <id>: <title>"`. For the one-time queue migration
    only, removing all remaining tracked `issues/` paths in the squash tree
    (`git rm -r --ignore-unmatch issues`) is the correct resolution when an
    already-committed finish leaves tracked queue paths; the new-prompt order
    normally does not conflict. The live queue is restored from the snapshot.
    Main stays untouched while conflicts are unresolved. Do no other queue or
    `/ship` work while the resolver runs.
  - **Resolver success gate:** independently verify in the acceptance worktree
    that there are no unmerged paths, `git rev-list --count PRE_MERGE..HEAD`
    is exactly `1`, `HEAD^ == PRE_MERGE`, status is clean, both suites pass
    (`python3 -m unittest discover -s tests` and
    `python3 -m unittest discover -s sandbox`), and the squash contains the
    issue branch's changed files. Any failed check is a failed acceptance.
  - **Fast-forward:** verify main is still at `PRE_MERGE` and clean outside the
    allowed local `issues/` paths. The unstaged deletion plus untracked new
    queue path survive the fast-forward (the target deletes the old tracked path
    and does not contain the new path); do NOT stage the queue move. If a user
    or orchestrator accidentally staged it, unstage with
    `git restore --staged issues` before the fast-forward (safe, no history
    rewrite) — the normal flow never stages. If main moved, discard the
    temporary worktree/branch and keep the issue in `review`. Otherwise run
    `git merge --ff-only accept/<id>-<slug>` in the main checkout and verify
    main's HEAD equals the squash SHA.
  - **Finish:** restore the queue snapshot (or confirm the surviving local
    move), verify the review file survives, `git ls-files issues` is empty and
    `git check-ignore` accepts the queue path, and `git status --porcelain` is
    clean. During the one-time migration, refresh the local `issues/README.md`
    and `issues/.gitignore` from
    `plugin/opencode-worktree/templates/issues/` (the tracked copies were
    removed by the migration). Move the issue to `completed` with
    `python3 .opencode/scripts/issue_queue.py complete "<exact filename>"` — a local
    move with **no commit** — then delete the temporary acceptance
    worktree/branch (`commitPending: false`, `deleteBranch: "always"`) and the
    issue worktree/branch (`deleteBranch: "always"`; after a squash the issue
    branch is not an ancestor of main, so `auto` would keep it). A deletion
    failure after completion is non-fatal and is reported.
  - **Committed-finish fallback:** if `finish` was already committed by an old
    session, or a manual bootstrap committed it, main is clean but still has a
    tracked `issues/review/<file>` path that the migration branch does not
    delete, so `git merge --squash` conflicts on queue paths. Resolve in the
    temporary acceptance worktree by removing all remaining tracked `issues/`
    paths (`git rm -r --ignore-unmatch issues`), then create the one commit
    `issue <id>: <title>`. `--ff-only` deletes the tracked queue files; restore
    the queue from the snapshot taken at accept time (review state), refresh
    `README.md`/`.gitignore` from the template, verify the queue is untracked
    and ignored, `complete` locally (no commit), and delete both
    worktrees/branches. Do NOT use the old merge-on-accept flow for 005: it
    deletes the on-disk queue and then its queue commit fails. Existing
    `issues:` commits (including a possible finish commit) remain in history;
    no rewrite. 005 may therefore have a pre-accept management commit in the
    old fallback; future acceptances add exactly one squash commit.
  - **Failure before the fast-forward:** delete the temporary acceptance
    worktree/branch (`commitPending: false`, `deleteBranch: "always"`) and
    keep the issue in `review` with its issue worktree/branch intact. No reset,
    clean, or history rewrite.
  - **Failure after the fast-forward:** do not reset; report the exact state
    so the user can decide.
- `reject <id>` — reject a `review` issue. Resolve its branch, then clean up
  BEFORE the local state move with `worktree_delete(branch, deleteBranch:
  "always", commitPending: false)` to discard abandoned WIP. If the tool says
  no worktree was found, probe the branch with `git rev-parse --verify --quiet
  refs/heads/<branch>`: absent -> proceed; present -> orphan branch, report
  blocked and leave state unchanged. Any other cleanup failure -> blocked and
  state unchanged. Then `python3 .opencode/scripts/issue_queue.py reopen "<exact
  filename>"` (local, **no commit**) and report why. `return` uses the same
  cleanup-before-move path before `python3 .opencode/scripts/issue_queue.py return
  "<exact filename>"`. Use the exact filename when a prefix is shared; if
  ambiguous, list the `review` filenames and ask the user which one to reject.

One prefix group per invocation by default (normally one issue). Never
implement, plan, review, or edit project files yourself; use only queue moves,
worktree tools, git checks, and test commands. Use
`python3 .opencode/scripts/issue_queue.py` for every state change; do not move issue
files by hand. Queue moves are local and create **no git commits**: never stage
or commit `issues/`, and never use a queue-state commit. Never push, and never
mark an issue complete without explicit user acceptance — agents never
self-accept.
