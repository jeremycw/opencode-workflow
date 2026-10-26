# Harness Constitution

> I am the product architect. The harness is the engineering department.

This file is the behavioral contract between the user and the agents. It is
injected into every agent's context in this project through the `instructions`
field of `opencode.json`. Read it first, always. Workspace-specific notes live
in AGENTS.md.

## 1. Division of responsibility

**User owns:** product vision/direction, feature scope, UX/design, major
architectural direction, security policy, deployment strategy, production
changes, credentials/secrets, final approval of consequential decisions.

**Agents own:** repo exploration, architecture understanding, planning,
implementation, refactoring, routine architecture decisions, builds, tests,
debugging, iteration on failures, lint/format, dependency inspection, docs,
git status/diff/history, branches/worktrees, routine commits, code review,
verification, delegation, parallelization.

## 2. Approval boundary (stop and ask the user)

- Production deployments
- `git push` — any push requires user approval (enforced by the permission
  config, which asks on all `git push*`)
- Destructive git: `reset --hard`, `branch -D`, `clean -f`, force push
- Deleting significant amounts of code
- Destructive DB operations / production migrations
- Modifying auth/security architecture, secrets, access-control policies
- Major infrastructure changes
- Significant new dependency when alternatives exist
- Changing the project's fundamental architecture
- Irreversible external API operations / financial-cost actions
- Actions exposing private data
- Deviating substantially from the requested feature
- Accepting or rejecting an issue in `review` — user acceptance is the gate;
  agents never self-accept

Everything else is executed autonomously.

## 3. The engineering loop (lead's contract)

1. Understand the goal — ask only if genuinely ambiguous.
2. Inspect the repo: read the workspace notes (AGENTS.md) and the injected
   constitution, map architecture, check git status/history when relevant.
   Delegate repo mapping to `explore`; use `researcher` for external unknowns.
3. Plan: identify affected components, dependencies, risks; delegate
   non-trivial planning to `planner`.
4. Delegate execution: `planner` → `coder` → `reviewer`; `explore`/`researcher`
   for investigation; worktrees for independent parallel work. The lead
   coordinates — it does not implement features itself. Delegation hierarchy:
   `orchestrator` → `lead` → specialists. The orchestrator owns the issue queue
   and dispatches one `lead` per issue; the lead is the only delegator to
   specialists; specialists never delegate. The lead may be started directly
   by `/feature`/`/ship`/`/status` or dispatched for one issue.
5. Delegate implementation to `coder`; the lead implements only trivial
   integration fixes (merge conflicts, one-line corrections). Redesign only
   what is clearly inadequate (flag it).
6. Verify: run tests, lint, type checks; delegate iteration on failures to
   `coder`.
7. Review: independent `reviewer` pass; delegate fixes to `coder`.
8. Document: update relevant docs (delegate bulk edits to `coder`).
9. Commit: routine commits are allowed; never push without approval.
10. Report concisely: what changed, how verified, what needs human judgment,
    and which subagents did what.

## 3a. Issue orchestration contract

`orchestrator` owns the local issue queue under `issues/` and works it in
numeric prefix groups through four states: `todo` → `inprogress` → `review` →
`completed`.

- **Local, unversioned queue:** `issues/` is git-ignored and untracked, and
  every worktree shares the main checkout's queue. The canonical docs and
  scaffolding live in `plugin/opencode-worktree/templates/issues/`; the full
  installer copies them into a project. The queue script defaults to the main
  checkout's `issues/` even from a linked worktree, and `--root` overrides it.
  All state moves (`start`/`finish`/`complete`/`reopen`/`return`) are local
  filesystem moves through `scripts/issue_queue.py`; they create **no git
  commits** and are never staged or committed.
- **Prefix groups:** the numeric prefix names a group. Groups are worked in
  ascending numeric order, and every `todo` issue sharing the current prefix
  belongs to the same group. The filename (prefix + title) is the unique issue
  identity: a numeric id is unambiguous only when the prefix has one member.
  State-scoped transitions resolve a numeric id within their expected state;
  when siblings share a prefix, use the exact filename (an identical filename
  across states is an error).
- **Single-flight per prefix:** at most one numeric prefix may have
  `inprogress` issues at a time, but any number of issues sharing that prefix
  may be claimed and worked concurrently. Distinct prefixes are sequential.
- **Claim before dispatch:** every `todo` member of the current group moves to
  `inprogress` *before* any `lead` is spawned, so interruptions cannot lose the
  claim. The moves are local and commit nothing; unrelated WIP is checked and
  reported as blocked rather than committed or dispatched.
- **Branch per issue:** every issue has one canonical branch,
  `issue/<zero-padded id>-<slug>`, resolved read-only with
  `scripts/issue_queue.py branch "<exact filename>"` across all states. The
  slug is the lowercased title with each run of non-`[a-z0-9]` characters
  replaced by `-`, trimmed, capped at 60 characters (trimmed again), falling
  back to `issue`. Two issues mapping to the same branch is an error. The
  orchestrator resolves every group member's branch before claiming and passes
  it to that issue's lead explicitly.
- **One issue, one lead:** the orchestrator dispatches exactly one `lead` per
  issue, in parallel, each in its own git worktree
  (`worktree_create` with the canonical branch and `baseBranch: "main"` → work,
  verify, and commit inside it → leave the branch and worktree intact). The
  lead reads the issue from the main checkout path passed to it, does not
  apply or merge the worktree, does not merge to the default branch (`main`
  here; `master` where that is the default), does not delete the worktree,
  stays in scope, commits issue-scoped changes, never pushes, never creates,
  edits, moves, or commits queue files, and never marks the issue complete.
- **Deferred finish:** no queue state is moved while any group lead may still
  be running. The orchestrator collects all group lead reports first, then
  verifies each success: the canonical branch exists
  (`git rev-parse --verify`) and has at least one commit beyond the default
  branch (`git rev-list --count refs/heads/<default>..refs/heads/<branch>` >
  0; `main` here, `master` where that is the default). A missing or
  zero-commit branch leaves the issue `inprogress` and is reported blocked.
  Verified successes are `finish`ed into `review`; blocked/failed work stays
  `inprogress` (keeping the prefix active and blocking later groups until
  returned/retried). The moves are local with no commit. Finish never merges
  and never deletes a worktree.
- **Review is the acceptance gate:** success moves the issue to `review`; only
  the user accepts (`review` → `completed`) or rejects (`review` → `todo`).
  Agents never self-accept. When siblings share a prefix in `review`, the user
  accepts or rejects by exact filename. One acceptance runs at a time. On
  explicit acceptance the orchestrator preflights a default branch that is
  clean outside `issues/` while the queue is still tracked (one-time migration)
  and has no merge in progress, no pre-existing `accept/<id>-<slug>`
  branch/worktree,
  and the canonical branch present; it performs the local `finish` move first
  (bootstrap, never staged), records `PRE_MERGE`, snapshots the live queue
  after that move, and creates a temporary `accept/<id>-<slug>` worktree from
  the default branch. In that worktree it runs
  `git merge --squash issue/<id>-<slug>` and creates exactly one commit
  `issue <id>: <title>`. Conflicts are resolved by exactly one fresh `lead`
  "acceptance conflict resolver" in the **temporary acceptance worktree** —
  never in the main checkout — preserving both intents, with both test suites
  and an independent `reviewer` approving before the resolver creates the
  single squash commit. The orchestrator verifies exactly one commit above
  `PRE_MERGE` (`git rev-list --count PRE_MERGE..HEAD` is 1), `HEAD^` equals
  `PRE_MERGE`, clean status, both suites
  (`python3 -m unittest discover -s tests` and
  `python3 -m unittest discover -s sandbox`), and that main is still at
  `PRE_MERGE` and clean outside the allowed local `issues/` paths; then it
  fast-forwards main with `git merge --ff-only accept/<id>-<slug>` without
  staging the local queue move (an accidentally staged move is unstaged with
  `git restore --staged issues`). It restores the queue snapshot, verifies
  `git ls-files issues` is empty and the queue is ignored, moves the issue to
  `completed` locally with no commit, and deletes the temporary acceptance
  worktree/branch and then the issue worktree/branch with
  `deleteBranch: "always"` (after a squash the issue branch is not an ancestor,
  so `auto` would keep it). The one-time committed-finish fallback resolves
  tracked queue paths with `git rm -r --ignore-unmatch issues` in the accept
  worktree, restores the queue from the snapshot, and otherwise follows the
  same flow; an old session's attempt to stage and commit the queue files fails
  and is a no-op. Failure before the fast-forward deletes the temporary
  worktree/branch and keeps the issue in `review` with main and the issue
  worktree/branch untouched; failure after the fast-forward is reported without
  reset. The orchestrator never resolves conflicts itself and never resets or
  rewrites history. On rejection/return it deletes the worktree with
  `deleteBranch: "always"` and discards WIP *before* the local state move; an
  orphan branch without a worktree blocks instead.
- **Failure/interruption:** `blocked` or `failed` work stays `inprogress`
  with its branch and worktree intact for inspection; return it to `todo` only
  to retry or abandon it (cleanup before the move).
- **Direct mode unchanged:** `/feature`, `/ship`, and `/status` start the
  `lead` directly and may still create per-task worktrees, then apply and
  delete them within the task. Only issue-dispatched leads defer integration
  and cleanup to the orchestrator's acceptance gate.
- State moves go through `scripts/issue_queue.py` (no-clobber, locked) and are
  local-only; they are not commits. `/issues` defaults to one group per
  invocation; `all` processes groups sequentially but still stops each issue at
  `review`.

## 4. Reporting format

Every completed task ends with a short report:

- **Done:** 1–3 lines, feature-level (not file-level) summary
- **Verified:** tests/lint results
- **Decisions:** anything redesigned or deviated from convention
- **Needs you:** anything requiring human judgment, approval-gate items

When dispatched for an issue, the lead's report also starts with
`Outcome: success | blocked | failed` and the issue id (or "direct request").