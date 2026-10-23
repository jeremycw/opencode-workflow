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
| `inprogress` | Claimed by the orchestrator and dispatched to exactly one `lead`. |
| `review` | Implementation finished; **awaiting user acceptance**. |
| `completed` | Explicitly accepted by the user. |

Only the transitions shown above are allowed. `start` refuses when another
issue is already `inprogress` (single-flight), and `complete` is only valid
from `review` — the orchestrator never self-accepts.

## Naming and order

- Filename format: `<numeric prefix> <title>.md`, e.g.
  `001 Add orchestrator agent.md`.
- The prefix must be at least three digits (`^(\d{3,})\s+(.+)\.md$`), and the
  title may contain spaces.
- Issues are worked in **numeric order** of the integer prefix: `002` comes
  before `010`, regardless of filename sorting.
- Duplicate numeric prefixes across any state are an error (ambiguous id).
- `README.md`, `.gitkeep`, `.gitignore`, hidden files, symlinks, and
  non-markdown files are ignored. Other `.md` files that do not match the
  naming scheme are ignored with a warning from `status`.

## Workflow invariants

1. **Numeric order** — lowest-numbered `todo` issue first; `start` refuses
   any other todo issue, so the ordering is enforced by the queue, not just
   by the prompt.
2. **Single-flight** — at most one issue in `inprogress` at a time.
3. **Claim before dispatch** — move `todo` -> `inprogress` *before* spawning
   the `lead` subagent, so an interruption cannot lose the claim.
4. **One issue, one `lead`** — the orchestrator dispatches one `lead` per
   issue; the lead must not edit or move `issues/`.
5. **Review is an acceptance gate** — success lands in `review`; only the user
   can accept it (`complete`) or reject it (`reopen`).
6. **Failure stays claimed** — `blocked`/`failed` work remains `inprogress`
   for inspection; use `return` to put it back in `todo`.
7. **Moves are no-clobber** — a mutation never overwrites an existing file.

## CLI

`scripts/issue_queue.py` (stdlib only) is the only supported way to move
issues. `--root <dir>` overrides the queue root (used by tests).

```bash
python3 scripts/issue_queue.py status          # counts + issues per state
python3 scripts/issue_queue.py list todo       # one state, numeric order
python3 scripts/issue_queue.py next            # lowest-numbered todo issue
python3 scripts/issue_queue.py start 001       # todo -> inprogress (claims it)
python3 scripts/issue_queue.py finish 001      # inprogress -> review
python3 scripts/issue_queue.py complete 001    # review -> completed (accept)
python3 scripts/issue_queue.py reopen 001      # review -> todo (reject)
python3 scripts/issue_queue.py return 001      # inprogress -> todo (failed)
```

An issue can also be addressed by its exact filename. Exit codes: `0` success,
`1` domain error (wrong state, duplicate/unknown id, no-clobber conflict), `2`
usage error. Mutations print the new repo-relative path; errors go to stderr as
`error: ...`.

The script locks `issues/.lock` around mutations when `fcntl` is available
(no-op fallback elsewhere), so two agents cannot claim work concurrently.

## Commands

- `/issues` or `/issues next` — work the next issue (one per invocation).
- `/issues all` — process `todo` sequentially; every issue still stops at
  `review`.
- `/issues status` — report the queue without changing it.
- `/issues accept <id>` — user acceptance: `review` -> `completed`.
- `/issues reject <id>` — rejection: `review` -> `todo`.
