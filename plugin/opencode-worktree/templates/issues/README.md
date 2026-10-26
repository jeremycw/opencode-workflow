# Issue Queue

This directory is the persistent work queue owned by the `orchestrator` agent.
Each issue is one markdown file; its queue state is its directory.

The queue is **local and unversioned**: `issues/` is git-ignored, untracked, and
shared by every worktree of the repository. State moves are plain filesystem
moves performed by `scripts/issue_queue.py`; they create no git commits and
never need one. The root `.gitignore` entry is the **root-anchored** `/issues/`
specifically so that `plugin/opencode-worktree/templates/issues/` stays tracked:
only the top-level queue is ignored, never a similarly named directory deeper
in the tree. This README is the canonical contract: in the harness checkout it
lives under `plugin/opencode-worktree/templates/issues/`, and the full installer
copies that scaffolding into a project's `issues/`. In an installed project the
only queue is the local `issues/` plus the installer-added `/issues/` ignore;
the template path is just the harness copy site. The queue state files in a
project are not tracked there either.

## States and transitions

```
                start                  finish                 complete
  todo ───────────────────► inprogress ─────────► review ──────────────► completed
   ▲      (claim before       │                     │
   │       dispatch)          │ return              │ reopen
   │                          ▼                     │ (reject)
   └──────────────────────────┴─────────────────────┘
```

| State | Meaning |
|---|---|
| `todo` | Ready to work; not yet claimed. |
| `inprogress` | Claimed by the orchestrator and dispatched to one `lead` per issue, each in its own worktree on its canonical branch. The lead commits there and never merges. |
| `review` | Implementation finished on the issue branch and **awaiting user acceptance**; the branch and worktree stay intact, unmerged. |
| `completed` | Explicitly accepted by the user and integrated into the default branch as one squash commit, then cleaned up. |

Only the transitions shown above are allowed. `start` refuses when a different
numeric prefix is already `inprogress` (single-flight per prefix), and
`complete` is only valid from `review` — the orchestrator never self-accepts.

## Naming and order

- Filename format: `<numeric prefix> <title>.md`, e.g.
  `001 Add orchestrator agent.md`.
- The prefix must be at least three digits (`^(\d{3,})\s+(.+)\.md$`), and the
  title may contain spaces.
- The numeric prefix names a **parallel group**. Issues sharing a prefix are
  distinct files (e.g. `001 Alpha.md` and `001 Beta.md`) and may be worked
  concurrently; different prefixes are worked sequentially.
- Groups are worked in **numeric order** of the integer prefix: the `001`
  group comes before `002`, and `002` before `010`, regardless of filename
  sorting.
- The filename is the unique issue identity. A numeric id is ambiguous when a
  group has more than one member, so use the **exact filename** for
  state-scoped operations on siblings.
- The same exact filename in two states is an error (ambiguous identity).
  Same-prefix files with different titles are allowed.
- `README.md`, `.gitkeep`, `.gitignore`, hidden files, symlinks, and
  non-markdown files are ignored. Other `.md` files that do not match the
  naming scheme are ignored with a warning from `status`.

## Workflow invariants

1. **Prefix groups in numeric order** — the lowest-numbered prefix is the
   current group; `start` refuses any later group, so the ordering is enforced
   by the queue, not just by the prompt.
2. **Single-flight per prefix** — at most one prefix may have issues in
   `inprogress`; every `todo` issue sharing that prefix is claimable in
   parallel. A group is not finished while any member remains `inprogress`;
   blocked/failed members keep the prefix active and block later groups until
   returned/retried.
3. **Claim the group before dispatch** — every member moves
   `todo` -> `inprogress` *before* spawning the `lead` subagents, so an
   interruption cannot lose a claim.
4. **One issue, one `lead`** — the orchestrator dispatches one `lead` per
   issue in parallel, each in its own worktree on its canonical branch
   (`worktree_create` -> work, verify, and commit inside -> leave the branch
   and worktree intact). The lead does not apply/merge the worktree, does not
   delete it, must not edit or move `issues/`, and never pushes.
5. **Local queue, no commits** — all state moves (`start`, `finish`,
   `complete`, `reopen`, `return`) are local filesystem moves. They create no
   git commits, require no commit, and must never be staged or committed. The
   queue script defaults to the **main checkout's** `issues/` even when run
   from a linked worktree (via the git common dir). Outside git (no `.git`
   marker) it falls back beside the script; inside a git worktree a git
   failure or timeout is an **error** with a clear message and the `--root`
   override, never a silent worktree-local split. `--root` overrides the root.
   Worktrees do not get a local queue copy; the orchestrator passes the main
   checkout's issue path to a dispatched lead or resolver.
6. **Review is the acceptance gate** — success lands in `review`; only the
   user can accept it (a squash acceptance) or reject it (which discards the
   worktree). When siblings share a prefix, use the exact filename.
7. **Failure stays claimed** — `blocked`/`failed` work remains `inprogress`
   for inspection and keeps blocking later groups; use `return` to put it back
   in `todo`.
8. **Moves are no-clobber** — a mutation never overwrites an existing file.
9. **Unrelated WIP blocks dispatch** — before dispatch the orchestrator checks
   `git status --porcelain`; if unrelated uncommitted/untracked changes remain,
   it returns the just-claimed issues to `todo` and reports a blocked dirty
   checkout instead of dispatching or committing user work. This check is not
   about committing queue moves — queue moves are never committed.
10. **One queue owner** — a single orchestrator invocation owns the queue.
    Concurrent `/issues` invocations can split a group (there is no atomic
    group-claim command); run one invocation at a time.
11. **Crash/partial-claim recovery** — after a crash or partial claim, an
    active `inprogress` group may contain claimed-but-undispatched issues;
    re-dispatch them or `return` them before retrying the group.

## Branches

Every issue has exactly one canonical git branch, derived deterministically
from its filename:

```
issue/<zero-padded id>-<slug>
```

In short, an issue's branch is `issue/<id>-<slug>`. The slug is the lowercased
title with every run of characters outside `[a-z0-9]` replaced by `-`,
leading/trailing dashes trimmed, capped at 60 characters (trimmed again), and
`issue` when nothing usable remains. For example `003 Use branches.md` ->
`issue/003-use-branches`.

- Resolve a branch read-only across **all** states with
  `python3 scripts/issue_queue.py branch "<exact filename>"` (a numeric id
  works only when that prefix has one member). Two issues mapping to the same
  branch is an error naming both filenames and the branch.
- An issue-dispatched `lead` works only inside
  `worktree_create(branch: "<canonical>", baseBranch: "main")`. Before
  creating anything it runs `git rev-parse --verify --quiet
  refs/heads/<canonical>` and inspects `worktree_list`; if either the branch or
  a worktree for it already exists, the lead reports `blocked` and does not
  create, reuse, or delete anything. The lead commits and runs tests inside
  the worktree but does **not** apply, merge to the default branch (`main`
  here; `master` where that is the default), or delete the worktree.
- `finish` does not merge: the orchestrator collects every group lead report,
  then requires the branch to exist (`git rev-parse --verify`) and to have at
  least one commit beyond the default branch
  (`git rev-list --count refs/heads/<default>..refs/heads/<branch>` > 0). A
  missing or zero-commit branch stays `inprogress` and is reported blocked.
- Starting a new group while `review` issues still have unmerged branches
  produces a **warning**, not a block; those branches are integrated only on
  acceptance.

## Squash acceptance

Acceptance is still user-only: agents never self-accept. When the user accepts
a `review` issue, the orchestrator integrates it as **exactly one squash
commit** on the default branch. The default branch is never merged into
directly from the issue branch, and existing issue-branch commits are not
preserved. One acceptance runs at a time.

1. **Preflight** in the main checkout: on the default branch (`main`, or
   `master` where that is the default), **clean outside `issues/` while the
   queue is still tracked (one-time migration)**, and no merge in progress. Run
   `git status --porcelain`: while `git ls-files issues` is non-empty (the
   one-time migration only), dirty paths under `issues/` are allowed (the local
   move's deleted tracked path plus untracked new path) and must not be staged
   or committed; every dirty path outside `issues/` blocks.
   After the migration `issues/` is ignored and this exception disappears
   naturally. Also require the canonical issue branch exists
   (`git rev-parse --verify --quiet refs/heads/<branch>`) and no pre-existing
   `accept/<id>-<slug>` branch or worktree. If an acceptance branch/worktree
   already exists, block; do not reuse or delete it.
2. For the one-time bootstrap, perform the local `finish` move first as a plain
   filesystem rename (never stage it, use `git mv`, or commit it). Then record
   `PRE_MERGE=$(git rev-parse HEAD)` and snapshot the live queue by copying
   `issues/` to a temporary directory outside the repo **after** the local
   finish move, so the snapshot contains the review state. The snapshot is
   required for the one-time migration and harmless afterwards.
3. Create a temporary worktree for acceptance from the default branch:
   `worktree_create(branch: "accept/<id>-<slug>", baseBranch: "main")`.
   (Use `master` as the base where that is the default.)
4. In that worktree run `git merge --squash issue/<id>-<slug>` and create
   exactly **one** commit, message `issue <id>: <title>`. In the new-prompt
   bootstrap this applies the migration deletion cleanly because main HEAD still
   has the old tracked queue path; an already-committed finish uses the fallback
   below.
5. **Conflicts** are resolved by exactly one fresh `lead` "acceptance
   conflict resolver" in the **temporary acceptance worktree** — never in the
   main checkout and never by merging there. It resolves in scope
   while preserving both sides' intent, stages the resolutions, runs both test
   suites, and gets independent `reviewer` approval before creating the single
   squash commit with `git commit -m "issue <id>: <title>"`. For the one-time
   queue migration only, removing all remaining tracked `issues/` paths in the
   squash tree (`git rm -r --ignore-unmatch issues`) is the correct
   resolution when an already-committed finish leaves tracked queue paths; the
   new-prompt order normally does not conflict. The live queue is restored from
   the snapshot. The main checkout stays untouched while conflicts are
   unresolved.
6. **Verify in the acceptance worktree**: exactly one commit above
   `PRE_MERGE` (`git rev-list --count PRE_MERGE..HEAD` is `1`), `HEAD^` equals
   `PRE_MERGE`, clean accept-worktree status, both suites green
   (`python3 -m unittest discover -s tests` and
   `python3 -m unittest discover -s sandbox`), and the squash contains the
   issue branch's changes.
7. **Fast-forward only**: verify main is still at `PRE_MERGE` and clean outside
   the allowed local `issues/` paths, then run
   `git merge --ff-only accept/<id>-<slug>` in the main checkout and verify
   main's HEAD equals the squash SHA. The unstaged deletion plus untracked new
   queue path survive the fast-forward (the target deletes the old tracked path
   and does not contain the new path); do NOT stage the queue move. If a user or
   orchestrator accidentally staged it, unstage with
   `git restore --staged issues` before the fast-forward (safe, no history
   rewrite) — the normal flow never stages. If main moved, discard the
   temporary worktree/branch and keep the issue in `review`.
8. **Restore the queue** from the snapshot (or confirm the surviving local
   move), then verify the review file survives, `git ls-files issues` is empty,
   `git check-ignore` accepts the queue path (`/issues/` is in the root
   `.gitignore`), and `git status --porcelain` is clean. During the one-time
   migration, refresh the local `issues/README.md` and `issues/.gitignore` from
   `plugin/opencode-worktree/templates/issues/` (the tracked copies were
   removed by the migration).
9. Move the issue to `completed` locally with
   `python3 scripts/issue_queue.py complete "<exact filename>"` — **no commit** —
   then delete the temporary acceptance worktree/branch
   (`deleteBranch: "always"`) and the issue worktree/branch
   (`deleteBranch: "always"`; after a squash the issue branch is not an
   ancestor of main, so `auto` would keep it).

Failure handling:

- **Before the fast-forward:** delete the temporary acceptance worktree/branch
  (`commitPending: false`, `deleteBranch: "always"`) and keep the issue in
  `review` with its issue worktree/branch intact. No reset, clean, or history
  rewrite.
- **After the fast-forward:** do not reset; report the exact state so the user
  can decide.
- A deletion failure after completion is non-fatal and is reported.

### Committed-finish fallback (old session or manual bootstrap)

If `finish` was already committed by an old session, or a manual bootstrap
committed it, main is clean but still has a tracked `issues/review/<file>` path
that the migration branch does not delete, so `git merge --squash` conflicts on
queue paths. Resolve in the temporary acceptance worktree by removing all
remaining tracked `issues/` paths (`git rm -r --ignore-unmatch issues`), then
create the one commit `issue <id>: <title>`. `--ff-only` deletes the tracked
queue files; restore the queue from the snapshot taken at accept time (review
state), refresh `README.md`/`.gitignore` from the template, verify the queue is
untracked and ignored, `complete` locally (no commit), and delete both
worktrees/branches.

Do NOT use the old merge-on-accept flow for 005: it deletes the on-disk queue
and then its queue commit fails. Existing `issues:` commits (including a
possible finish commit) remain in history; no rewrite. 005 may therefore have a
pre-accept management commit in the old fallback; future acceptances add
exactly one squash commit.

## Rejection, return, and orphans

On rejection/`return`, delete the worktree with
`deleteBranch: "always", commitPending: false` *before* the local state move,
so abandoned WIP is discarded. If no worktree exists but the branch does, that
orphan branch blocks the move and is reported; it is never auto-deleted. The
state move itself is local and creates no commit.

## CLI

`scripts/issue_queue.py` (stdlib only) is the only supported way to move
issues. Mutations are pure local filesystem moves — **no git commits**. The
script defaults to the main checkout's queue even from a linked worktree.
Outside git (no `.git` marker) it falls back beside the script; inside a git
worktree a git failure or timeout is an **error** with a clear message and the
`--root` override, never a silent worktree-local split. `--root <dir>` overrides
the queue root (used by tests and for an explicit checkout).

```bash
python3 scripts/issue_queue.py status                 # counts + issues per state
python3 scripts/issue_queue.py list todo              # one state, numeric order
python3 scripts/issue_queue.py next                   # lowest-numbered todo (informational)
python3 scripts/issue_queue.py next-group             # all claimable todo issues in the current group
python3 scripts/issue_queue.py branch "001 Alpha.md"  # canonical branch, resolved in any state
python3 scripts/issue_queue.py start "001 Alpha.md"   # todo -> inprogress (claims it)
python3 scripts/issue_queue.py start "001 Beta.md"    # same-prefix sibling may also start
python3 scripts/issue_queue.py finish "001 Alpha.md"  # inprogress -> review
python3 scripts/issue_queue.py complete "001 Alpha.md" # review -> completed (accept, local)
python3 scripts/issue_queue.py reopen "001 Alpha.md"  # review -> todo (reject)
python3 scripts/issue_queue.py return "001 Alpha.md"  # inprogress -> todo (failed)
```

An issue can be addressed by a numeric prefix only when that prefix has one
member in the expected state; otherwise pass the exact filename (quote it, it
contains spaces). Exit codes: `0` success, `1` domain error (wrong state,
ambiguous/unknown id, duplicate branch, no-clobber conflict), `2` usage error.
Mutations print the new repo-relative path; `branch` prints only the branch
name; errors go to stderr as `error: ...`.

The script locks `issues/.lock` around mutations when `fcntl` is available
(no-op fallback elsewhere), so two agents cannot claim work concurrently.

## Commands

- `/issues` or `/issues next` — work the current prefix group (one group per
  invocation, normally one issue). Every todo member is claimed before one
  `lead` per issue is dispatched in parallel worktrees.
- `/issues all` — process groups sequentially; within a group every issue runs
  in parallel, and every issue still stops at `review`.
- `/issues status` — report the queue without changing it.
- `/issues accept <id>` — user acceptance: preflight clean main outside
  `issues/` while the queue is still tracked (one-time migration) and no
  acceptance branch/worktree, perform the local `finish` move first (bootstrap,
  never staged), snapshot the queue after that move, create the temporary
  `accept/<id>-<slug>` worktree, `git merge --squash` the issue branch, create
  one commit, resolve conflicts in that worktree through one fresh `lead`
  resolver, verify exactly one commit above `PRE_MERGE` and both suites,
  fast-forward main with `--ff-only` (never staging the local queue move),
  restore the queue, refresh the template README/.gitignore during the
  migration, `complete` locally, and delete both worktrees/branches with
  `deleteBranch: "always"`. Any failure before the fast-forward keeps the
  issue in `review` with main untouched. Use the exact filename when a prefix
  is shared. An already-committed finish uses the committed-finish fallback.
- `/issues reject <id>` — rejection: delete the worktree/branch
  (`deleteBranch: "always"`, discarding WIP) *before* `reopen`
  (`review` -> `todo`). An orphan branch without a worktree blocks instead.
  Use the exact filename when a prefix is shared.

## Installer and template notes

The full installer copies `plugin/opencode-worktree/templates/issues/` into the
target project's `issues/` and ensures the target's root `.gitignore` gains the
root-anchored entry `/issues/` (backup/append, never clobbering the existing
file), so only the top-level queue is ignored and
`plugin/opencode-worktree/templates/issues/` stays tracked in the harness
checkout. In an installed project there is no template path: it just has its
local `issues/` plus the installer-added `/issues/` ignore. The local queue is
then untracked. If the target already tracks `issues/`, the installer warns and
the user runs `git rm -r --cached issues` (one-time migration); queue moves
themselves never commit.

## Migration/bootstrap (issue 005)

Before this change, `main` tracked `issues/` and accepted issues with a merge
on main. The 005 migration commit removes the queue from the index
(`git rm -r --cached issues`) and adds `/issues/` to the root `.gitignore`.
Merging or fast-forwarding that branch onto `main` therefore removes the
formerly tracked queue files from main's working tree. An old session's attempt
to stage and commit the queue files fails and is a no-op because they are now
ignored: **never use `git add -f`**; the local queue state is authoritative.

### Preferred new-prompt bootstrap (no extra queue commit)

After restart with the new prompt, the one-time bootstrap is:

1. `finish` remains a local, unstaged filesystem move (plain rename; do NOT run
   `git add`, `git mv`, or a commit). On pre-migration main this leaves only
   `issues/` paths dirty: the old tracked path deleted and the new path
   untracked. That is the expected local queue move, not unrelated WIP.
2. Acceptance preflight requires clean `git status --porcelain` outside
   `issues/` and no merge in progress. While `git ls-files issues` is non-empty
   (the one-time migration only), dirty paths under `issues/` are allowed and
   must not be staged or committed. After the migration, `issues/` is ignored
   and this exception disappears naturally.
3. Record `PRE_MERGE` and snapshot the live queue **after** the local finish
   move (so the snapshot contains the review state).
4. Create the temporary `accept/<id>-<slug>` worktree from main HEAD.
   `git merge --squash issue/<id>-<slug>` applies the migration deletion cleanly
   because main HEAD still has the old tracked queue path; create exactly one
   commit `issue <id>: <title>`.
5. Verify exactly one commit above `PRE_MERGE`, `HEAD^ == PRE_MERGE`, a clean
   accept worktree, and both suites.
6. Verify main is still at `PRE_MERGE` and clean outside the allowed `issues/`
   local paths; `git merge --ff-only accept/<id>-<slug>`. The unstaged deletion
   plus untracked new queue path survive the fast-forward (the target deletes
   the old tracked path and does not contain the new path); do NOT stage the
   queue move. If a user or orchestrator accidentally staged it, unstage with
   `git restore --staged issues` before the fast-forward (safe, no history
   rewrite) — the normal flow never stages.
7. After the fast-forward: verify the queue review file survives,
   `git ls-files issues` is empty, `/issues/` is ignored, and
   `git status --porcelain` is clean. Restore/refresh the local
   `issues/README.md` and `issues/.gitignore` from
   `plugin/opencode-worktree/templates/issues/` (the tracked copies were
   removed by the migration). Then `complete` locally (no commit), delete the
   temporary accept worktree/branch, then the issue worktree/branch with
   `deleteBranch: "always"`.

### Committed-finish fallback (old session or manual bootstrap)

If `finish` was already committed by an old session, or a manual bootstrap
committed it, main is clean but has a tracked `issues/review/<file>` path that
the migration branch does not delete, so `git merge --squash` conflicts on queue
paths. Resolve in the accept worktree by removing all remaining tracked
`issues/` paths (`git rm -r --ignore-unmatch issues`), then create the one
commit `issue <id>: <title>`. `--ff-only` deletes the tracked queue files;
restore the queue from the snapshot taken at accept time (review state), refresh
`README.md`/`.gitignore` from the template, verify the queue is untracked and
ignored, `complete` locally (no commit), and delete both worktrees/branches.

Do NOT use the old merge-on-accept flow for 005: it deletes the on-disk queue
and then its queue commit fails. Existing `issues:` commits (including a
possible finish commit) remain in history; no rewrite. 005 may therefore have a
pre-accept management commit in the old fallback; future acceptances add
exactly one squash commit.
