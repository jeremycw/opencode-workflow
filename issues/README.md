# Issue Queue

This directory is the persistent work queue owned by the `orchestrator` agent.
Each issue is one markdown file; its queue state is its directory.

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
| `completed` | Explicitly accepted by the user, merged into the default branch, and cleaned up. |

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
5. **Review is an acceptance gate** — success lands in `review`; only the user
   can accept it (`complete`, which merges the branch) or reject it (`reopen`,
   which discards the worktree). When siblings share a prefix, use the exact
   filename.
6. **Failure stays claimed** — `blocked`/`failed` work remains `inprogress`
   for inspection and keeps blocking later groups; use `return` to put it back
   in `todo`.
7. **Moves are no-clobber** — a mutation never overwrites an existing file.
8. **Clean main for merges** — the orchestrator commits the claim batch
   (issue-state moves only) before dispatch. It then checks
   `git status --porcelain`; if unrelated WIP remains, it returns the
   just-claimed issues and reports a blocked dirty checkout instead of
   dispatching or committing user work. After all group leads report, it
   verifies each success branch (exists — `git rev-parse --verify` — and has
   `git rev-list --count refs/heads/<default>..refs/heads/<branch>` > 0, at
   least one commit beyond the default branch) and commits the `finish` moves
   for successes only; no merge or worktree deletion happens at finish.
   Merging happens only at acceptance,
   after preflighting a clean main on the default branch.
9. **One queue owner** — a single orchestrator invocation owns the queue.
   Concurrent `/issues` invocations can split a group (there is no atomic
   group-claim command); run one invocation at a time.
10. **Crash/partial-claim recovery** — after a crash or partial claim, an
    active `inprogress` group may contain claimed-but-undispatched issues;
    re-dispatch them or `return` them before retrying the group.

## Branches and acceptance

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
  produces a **warning**, not a block; those branches merge only on acceptance.
- On acceptance, the orchestrator preflights a clean main on the default
  branch, merges with `worktree_apply(branch, mode: "merge")`, runs both test
  suites, then `complete`s the issue and
  `worktree_delete(branch, deleteBranch: "auto")`. A conflict (or a real merge
  in progress) is aborted and reported; the issue stays in `review` with its
  worktree intact. The orchestrator never resolves conflicts or resets main.
- On rejection/return, the worktree is deleted with
  `deleteBranch: "always", commitPending: false` *before* the state move, so
  abandoned WIP is discarded. If no worktree exists but the branch does, that
  orphan branch blocks the move and is reported; it is never auto-deleted.

## CLI

`scripts/issue_queue.py` (stdlib only) is the only supported way to move
issues. `--root <dir>` overrides the queue root (used by tests).

```bash
python3 scripts/issue_queue.py status                 # counts + issues per state
python3 scripts/issue_queue.py list todo              # one state, numeric order
python3 scripts/issue_queue.py next                   # lowest-numbered todo (informational)
python3 scripts/issue_queue.py next-group             # all claimable todo issues in the current group
python3 scripts/issue_queue.py branch "001 Alpha.md"  # canonical branch, resolved in any state
python3 scripts/issue_queue.py start "001 Alpha.md"   # todo -> inprogress (claims it)
python3 scripts/issue_queue.py start "001 Beta.md"    # same-prefix sibling may also start
python3 scripts/issue_queue.py finish "001 Alpha.md"  # inprogress -> review
python3 scripts/issue_queue.py complete "001 Alpha.md" # review -> completed (accept)
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
- `/issues accept <id>` — user acceptance: preflight a clean main on the
  default branch, `worktree_apply` the canonical branch in `merge` mode, run
  both test suites, then `complete` (`review` -> `completed`) and delete the
  merged worktree/branch. A conflict or red suite keeps it in `review` and is
  reported. Use the exact filename when a prefix is shared.
- `/issues reject <id>` — rejection: delete the worktree/branch
  (`deleteBranch: "always"`, discarding WIP) *before* `reopen`
  (`review` -> `todo`). An orphan branch without a worktree blocks instead.
  Use the exact filename when a prefix is shared.
