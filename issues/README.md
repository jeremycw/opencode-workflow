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
| `inprogress` | Claimed by the orchestrator and dispatched to one `lead` per issue, each in its own worktree. |
| `review` | Implementation finished; **awaiting user acceptance**. |
| `completed` | Explicitly accepted by the user. |

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
   issue in parallel, each in its own worktree (`worktree_create` -> work,
   verify, and commit inside -> `worktree_apply` with merge ->
   `worktree_delete`). The lead must not edit or move `issues/` and never
   pushes.
5. **Review is an acceptance gate** — success lands in `review`; only the user
   can accept it (`complete`) or reject it (`reopen`). When siblings share a
   prefix, use the exact filename.
6. **Failure stays claimed** — `blocked`/`failed` work remains `inprogress`
   for inspection and keeps blocking later groups; use `return` to put it back
   in `todo`.
7. **Moves are no-clobber** — a mutation never overwrites an existing file.
8. **Clean main for merges** — the orchestrator commits the claim batch
   (issue-state moves only) before dispatch, because `worktree_apply` refuses a
   dirty main. It then checks `git status --porcelain`; if unrelated WIP
   remains, it returns the just-claimed issues and reports a blocked dirty
   checkout instead of dispatching or committing user work. After all group
   leads report, it commits the `finish` moves for successes only; no
   queue-state commit happens while a merge may be pending.
9. **One queue owner** — a single orchestrator invocation owns the queue.
   Concurrent `/issues` invocations can split a group (there is no atomic
   group-claim command); run one invocation at a time.
10. **Crash/partial-claim recovery** — after a crash or partial claim, an
    active `inprogress` group may contain claimed-but-undispatched issues;
    re-dispatch them or `return` them before retrying the group.

## CLI

`scripts/issue_queue.py` (stdlib only) is the only supported way to move
issues. `--root <dir>` overrides the queue root (used by tests).

```bash
python3 scripts/issue_queue.py status                 # counts + issues per state
python3 scripts/issue_queue.py list todo              # one state, numeric order
python3 scripts/issue_queue.py next                   # lowest-numbered todo (informational)
python3 scripts/issue_queue.py next-group             # all claimable todo issues in the current group
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
ambiguous/unknown id, no-clobber conflict), `2` usage error. Mutations print
the new repo-relative path; errors go to stderr as `error: ...`.

The script locks `issues/.lock` around mutations when `fcntl` is available
(no-op fallback elsewhere), so two agents cannot claim work concurrently.

## Commands

- `/issues` or `/issues next` — work the current prefix group (one group per
  invocation, normally one issue). Every todo member is claimed before one
  `lead` per issue is dispatched in parallel worktrees.
- `/issues all` — process groups sequentially; within a group every issue runs
  in parallel, and every issue still stops at `review`.
- `/issues status` — report the queue without changing it.
- `/issues accept <id>` — user acceptance: `review` -> `completed`. Use the
  exact filename when a prefix is shared.
- `/issues reject <id>` — rejection: `review` -> `todo`. Use the exact
  filename when a prefix is shared.
