Stop committing issue-management state to `main`, and make acceptance produce one
squash commit per issue.

## Problem

Every issue currently produces management commits on `main`:

- `issues: claim <group>` before dispatch
- `issues: finish <group>` when work moves to review
- `issues: accept <issue>` when the user accepts

Acceptance also uses `worktree_apply(branch, mode: "merge")`, which creates a
merge commit and preserves every commit from the issue branch. The result is
that `main` contains both issue-management commits and multi-commit issue
history.

Desired future behaviour: after an issue is accepted, `main` contains exactly
one new commit for that issue (a squash commit) and no `issues:` management
commits. Existing management commits already in history are acceptable and
must NOT be rewritten.

## Direction

Move queue state off `main` using the **local, unversioned queue** option:

- `issues/` stays on disk and visible in the working tree.
- Add `issues/` to `.gitignore` and stop tracking it (one-time migration
  commit). Queue moves then create no commits.
- The queue script resolves the main checkout's queue even when invoked from an
  issue worktree, so all worktrees share one queue.
- The versioned `issue-queue` branch/worktree is an alternative, not the
  default for this issue.

Do not rewrite history. Do not remove existing `issues:` commits from `main`.

## Acceptance flow

Replace the current merge-on-main acceptance with a squash staged in a
temporary worktree:

1. Preflight: clean `main`, on the default branch, issue branch exists; record
   `PRE_MERGE`.
2. Create a temporary `accept/<id>-<slug>` worktree from `main`.
3. In that worktree, run `git merge --squash issue/<id>-<slug>` and create one
   commit for the issue (message: `issue <id>: <title>`).
4. If conflicts occur, dispatch the existing acceptance conflict-resolver
   `lead` in the temporary worktree (not `main`). It resolves, stages, runs
   both suites, and gets independent `reviewer` approval. `main` stays
   untouched while the resolution is unresolved.
5. Verify: exactly one commit on top of `PRE_MERGE`, clean worktree, both
   suites green (`tests/` and `sandbox/`).
6. Fast-forward `main` to the squash commit (`git merge --ff-only`). If `main`
   moved, discard the acceptance worktree and keep the issue in `review`.
7. Move the issue to `completed` in the local queue (no commit), delete the
   temporary worktree/branch, then delete the issue worktree/branch with
   `deleteBranch: "always"` (after a squash the issue branch is no longer an
   ancestor, so `auto` would keep it).

On any failure before the fast-forward, delete the temporary worktree/branch
and keep the issue in `review` with its worktree and branch intact. No reset,
clean, or history rewrite.

## Implementation notes

- Remove all queue-state `git add issues && git commit` instructions from the
  orchestrator and `/issues` acceptance/finish/claim flows.
- Keep the pre-dispatch unrelated-WIP check, but issue moves no longer require
  a commit to keep `main` clean.
- The queue script should default to the main checkout's `issues/` queue when
  run from an issue worktree.
- The installer/scaffolding must create a local `issues/` queue and ensure it
  is ignored, not tracked.
- No worktree-plugin change is required: create/delete the temporary
  acceptance worktree with the existing `worktree_create` /
  `worktree_delete` tools and run `git merge --squash` in that worktree.
- Update the orchestrator, `issues` command, lead conflict-resolver mode,
  constitution, README, issues README, PLAN, and validation docs to describe
  the off-main queue and squash acceptance.
- Add a deterministic stdlib git integration test: build a temp repo with an
  issue branch containing at least two commits, run the squash acceptance
  mechanics, and assert `main` has exactly one new commit, the issue branch is
  deleted, the worktree is removed, and the queue state moved without a commit.

## Acceptance criteria

- Accepting a future issue adds exactly one commit to `main` and no `issues:`
  commit.
- The squash commit contains every implementation commit from that issue
  branch.
- Queue files are not tracked on `main` (local-queue option).
- A conflicting acceptance is resolved in the temporary worktree; failure
  leaves `main` unchanged and the issue in `review`.
- Both test suites pass after acceptance, and the issue branch/worktree are
  deleted.
- Existing `issues:` commits remain in history; no history rewrite occurs.
