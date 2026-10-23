# OpenCode Engineering Harness

> "I am the product architect. The harness is the engineering department."

A thin engineering-operating layer on top of [opencode](https://opencode.ai)
that turns it from an AI-powered text editor into an engineering team you can
delegate feature-level objectives to. You say **what + why**; the harness
determines **how** — inspect, plan, implement, test, review, document, commit —
and closes the loop itself.

This repository is the **staging ground**: everything here is exercised and
validated before being packaged into a copyable template (see `PLAN.md`,
Phase 5). Nothing is promoted to the global opencode config.

---

## How it works

```
                    USER (product owner)
                             │  "/issues" | "/feature Add OAuth login…"
                             ▼
              ┌───────────────────────────────┐
              │     orchestrator (primary)     │
              │  owns issues/, claims a prefix │
              │  group, one lead per issue in  │
              │  parallel worktrees            │
              └───────────────┬───────────────┘
                              │  task: only lead
                              ▼
              ┌───────────────────────────────┐
              │         lead (mode: all)       │
              │  engineering loop, delegates   │
              │  via permission: task          │
              └───┬───────┬───────┬───────┬────┘
                  │       │       │       │
                  ▼       ▼       ▼       ▼
             planner   coder  reviewer researcher
            (subagent)(subagent)(subagent)(subagent)
             non-code edits full tools non-code edits non-code edits
                         │       │
                         ▼       ▼
                  tests/lint  verification
                         │       │
                         └───┬───┘
                             ▼
                  git commits (never push)
                             │
                             ▼
                    USER REVIEW ("Good. Next…")
```

Delegation is two levels deep (`subagent_depth: 2`): `orchestrator` → `lead` →
specialists. The orchestrator dispatches; the lead coordinates; specialists
never delegate. `/feature`, `/ship`, and `/status` start `lead` directly.

Three layers make this work:

| Layer | Where | Role |
|---|---|---|
| **Constitution** | `.opencode/constitution.md` | Behavioral contract — division of responsibility, approval boundary, the engineering loop, issue orchestration. Injected into **every** agent via the `instructions` field in `opencode.json` (no agent has to read it). |
| **Agents** | `.opencode/agents/*.md` | The team: primary `orchestrator` (queue owner), `lead` (mode `all`), and four specialized subagents. |
| **Commands** | `.opencode/commands/*.md` | User-facing entry points: `/issues`, `/feature`, `/ship`, `/status`. |

`AGENTS.md` at the repo root holds workspace-specific notes only (project
facts, conventions) — a copied harness leaves it clear for the new project's
own instructions.

## The engineering loop

`lead` runs this loop for every feature-level request:

```
 1. Understand ──► 2. Inspect ──► 3. Plan ──► 4. Delegate ──► 5. Execute
     the goal        the repo      (components,   (planner → coder →   (subagents
     (ask only if     (architecture,  deps, risks)   reviewer; parallel   implement;
      ambiguous)      git state)                     when independent;    lead
                                                     worktrees for        coordinates)
                                                     isolation)
                                                            │
                                                            ▼
 10. Report ◄── 9. Commit ◄── 8. Document ◄── 7. Review ◄── 6. Verify
 (Done/Verified/   (routine,        (update docs)   (independent   (tests, lint,
  Decisions/       NEVER push)                       reviewer pass) type checks)
  Needs you)
```

**Approval boundary** — agents stop and ask the user only for: deploys, push to
protected branches, destructive git/DB operations, security/auth changes,
secrets, major new dependencies, architecture changes, substantial deviations
from the request, and accepting/rejecting an issue in `review`. Everything else
runs autonomously.

## Delegation & coordination

The lead is an **orchestrator, not an implementer** — it delegates execution
to subagents and coordinates from their reports. Each subagent's final
message is shaped for the lead's next decision:

| Work | Subagent | Returns to the lead |
|---|---|---|
| Codebase lookup | `explore` | concise answer to the question |
| External research | `researcher` | answer, evidence (citations), recommendation, unresolved items |
| Architecture / planning | `planner` | complete plan — handed to `coder` as the implementation brief |
| Implementation + tests | `coder` | what changed, verification results, deviations, reviewer focus |
| Independent review | `reviewer` | verdict (approve / needs fixes), prioritized findings, recommendation |

Specialists never delegate — the lead is the only delegator to them; the
orchestrator may task the lead. For direct-mode work (`/feature`-style),
independent tasks run in parallel worktrees: one worktree per task, one `coder`
per worktree, merged back with `worktree_apply`. An issue-dispatched lead works
inside its single issue worktree on the canonical issue branch and never
merges; the orchestrator merges only after user acceptance.

## Issue workflow

`issues/` is a persistent queue owned by the `orchestrator` agent and moved
only by `scripts/issue_queue.py`:

```
todo ──start──► inprogress ──finish──► review ──complete──► completed
                  │                       │
                  └──return──► todo       └──reopen──► todo
```

- **Prefix groups:** the integer prefix names a group; groups are worked in
  ascending order (`001` before `002`, `002` before `010`). Same-prefix files
  with distinct titles (e.g. `001 Alpha.md`, `001 Beta.md`) form one parallel
  group.
- **Single-flight per prefix:** at most one prefix may have `inprogress`
  issues, but every issue sharing that prefix may run concurrently; distinct
  prefixes stay sequential. A group is not finished while any member remains
  `inprogress`; blocked/failed members keep it active and block later groups
  until returned/retried.
- **Claim the group before dispatch:** the orchestrator resolves every member's
  canonical branch first (read-only), then moves every `todo` member of the
  group to `inprogress` *before* spawning one `lead` per issue. If a lookup or
  claim fails, or unrelated WIP dirties main, it returns the just-claimed
  issues to `todo` and reports instead of dispatching.
- **One issue, one branch/worktree:** each issue has a canonical branch
  `issue/<id>-<slug>`; each lead works only there
  (`worktree_create` -> work/verify/commit inside -> leave branch and worktree
  intact). The orchestrator dispatches leads in parallel; an issue-dispatched
  lead never applies, merges, or deletes the worktree.
- **Clean main for merges:** the orchestrator commits only the claim batch
  before dispatch, checks for unrelated WIP before dispatching, collects every
  group lead report, then verifies each success branch exists and has at
  least one commit beyond the default branch
  (`git rev-list --count refs/heads/<default>..refs/heads/<branch>` > 0)
  before committing the `finish` moves in one batch. Finish never merges or
  deletes a worktree.
- **One queue owner:** run one `/issues` invocation at a time; concurrent
  invocations can split a group because there is no atomic group-claim command.
- **Review is the acceptance gate:** a successful lead report moves the issue
  to `review` with its branch unmerged; only the user accepts (`completed`,
  which merges the branch and cleans up) or rejects (`todo`, which discards the
  worktree). Agents never self-accept; with same-prefix siblings,
  accept/reject by exact filename.
- **Failure/interruption:** `blocked`/`failed` work stays `inprogress` with its
  worktree intact, keeps blocking later groups, and is reported; `return`
  cleans up the worktree/branch before putting it back in `todo` to retry or
  abandon.

```bash
python3 scripts/issue_queue.py status          # queue counts + issue paths
python3 scripts/issue_queue.py next-group      # every claimable todo in the current group
python3 scripts/issue_queue.py branch "001 A.md" # canonical branch (any state)
python3 scripts/issue_queue.py start "001 A.md" # claim before dispatch (exact filename)
python3 scripts/issue_queue.py finish "001 A.md" # success -> review (no merge)
python3 scripts/issue_queue.py complete "001 A.md" # user acceptance only (merge + cleanup)
```

See `issues/README.md` for the full contract and file naming rules. State moves
are no-clobber and locked through `issues/.lock`.

## Agents

All agents live in `.opencode/agents/`. `orchestrator` is the default primary
agent; `lead` runs in `all` mode so it can be started directly by a command or
dispatched by the orchestrator. The rest are subagents.

| Agent | Mode | Role | Access |
|---|---|---|---|
| **`orchestrator`** | primary | Issue queue owner. Works numeric prefix groups in ascending order, resolves canonical branches, claims every member of the active group before dispatch, sends one `lead` per issue in parallel worktrees, and moves success to `review` without merging. On acceptance it merges with `worktree_apply`, verifies both suites, and deletes the merged worktree/branch. Does not implement or plan. | `edit`: **deny**; `todowrite`: allow; `task`: only `lead` (all else denied); `bash`: `*` → allow, with push/reset/branch-delete/clean/`rm -rf*`/publish and `issue_queue.py complete`/`reopen` → **ask** |
| **`lead`** | all | Engineering lead. Takes feature-level objectives (directly or dispatched for one issue), runs the loop by delegating execution to subagents, coordinates from their reports, verifies, commits. Issue-dispatched, it works inside its canonical issue branch/worktree and never merges or deletes it. | `todowrite`: allow; `task`: only `planner`, `coder`, `reviewer`, `researcher`, `explore` (all else denied). `bash`: everything allowed **except** `git push*`, `git reset --hard*`, `git branch -D*`, `git clean -f*`, `git push --force*`, `rm -rf*` → **ask** |
| **`planner`** | subagent | Architecture & planning. Maps the codebase, produces file-level implementation plans with tests and risks. | `edit` allowed for plans/notes/docs (no source changes); `bash` unrestricted except destructive git/`rm -rf*`/`npm publish*` → **ask**; `webfetch` allowed |
| **`coder`** | subagent | Implementation. Writes production-quality code, runs tests/lint, iterates until green. | Full `bash` access **except** `git push*`, `git reset --hard*`, `git clean -f*`, `git branch -D*` → **deny** |
| **`reviewer`** | subagent | Independent review. Reads the diff with fresh eyes, checks correctness/security/regressions, runs tests itself. | `edit` allowed for non-code files (no fixes); `bash` unrestricted except destructive git/`rm -rf*`/`npm publish*` → **ask** |
| **`researcher`** | subagent | Research. Investigates dependencies, APIs, external docs with citations. | `edit` allowed for notes/docs (no code changes); `bash` unrestricted except destructive git/`rm -rf*`/`npm publish*` → **ask**; `webfetch` + `websearch` allowed |

Built-in opencode agents (`explore`, `build`, `general`, `scout`, …) remain
available; `lead` may delegate to `explore` for fast codebase lookups, and
`build` stays as the escape hatch.

### Global permission safety net (`opencode.json`)

Applies to every agent as a last-match-wins layer: `bash` `*` → allow, with
**ask** on `git push*` (all pushes — a bare `git push` cannot bypass the
gate), `git reset --hard*`, `git branch -D*`, `git clean -f*`,
`git push --force*`, `rm -rf*`, `npm publish*`. `webfetch`/`websearch` → allow.
`external_directory` defaults to **ask** except `~/.local/share/opencode/worktree/**`
→ allow, so work inside worktrees does not prompt; `doom_loop` → allow; the six
`worktree_*` tools (`create`, `apply`, `delete`, `list`, `gc`,
`resolve_conflicts`) are pinned to allow.

## Commands

User-facing entry points: `/issues` routes to the `orchestrator`; the rest
route to `lead`.

| Command | Purpose |
|---|---|
| `/issues [status\|next\|all\|accept <id>\|reject <id>]` | Work the issue queue. Default is one prefix group: resolve canonical `issue/<id>-<slug>` branches, claim every member (`todo` → `inprogress`) before dispatch, send one `lead` per issue in parallel worktrees that never merge, stop at `review` with branches intact. `all` processes groups sequentially but still stops every issue at `review`; `accept` merges the branch, runs both suites, completes, and deletes the worktree; `reject` discards the worktree/branch before returning to `todo` (exact filename when a prefix is shared). |
| `/feature <request>` | Start a feature-level request: "Add user authentication using OAuth…". Delegation-first: `lead` coordinates; `explore`/`planner`/`coder`/`reviewer`/`researcher` execute; independent tasks run in parallel worktrees. |
| `/ship` | Close out current work: apply pending direct-mode worktrees (never unaccepted issue branches), verify, review (`explore` state check + `reviewer` pass + `coder` fixes), update docs, create routine commits. **Never pushes.** |
| `/status` | Brief repo/git state: current branch, uncommitted changes, recent commits, work in progress, worktree state, and issue queue status. |

## Worktree plugin (parallel isolation)

The forked worktree plugin gives `lead` git-worktree isolation for independent
tasks — **without spawning any terminals** (Termux-safe): work happens via
bash/`worktree_apply`, not a new terminal window.

| Tool | Purpose |
|---|---|
| `worktree_create` | Create an isolated worktree for a task |
| `worktree_apply` | Merge child worktree changes back into the main checkout — `merge` (conflict file-list report) or `overwrite`; `noFF` forces a merge commit |
| `worktree_delete` | Remove a worktree; `deleteBranch: auto/always/never`; `commitPending: false` discards changes |
| `worktree_gc` | Prune stale/abandoned worktrees — `dryRun` preview, `maxAgeDays` override, report of pruned/unregistered/kept |
| `worktree_list` | List worktrees, reconciled with git (git-only worktrees shown as `(unregistered)`, expired flagged `*`) |
| `worktree_resolve_conflicts` | Resolve a pending merge: `ours`/`theirs` (resolve + stage, finish with `git commit`) or `abort` |

> **Note:** the plugin is now installed at the project-scoped path
> `.opencode/plugin/` and auto-discovered by opencode (its loader globs
> top-level `{plugin,plugins}/*.{ts,js}` under the config dir — no
> `opencode.json` entry is needed). `.opencode/plugin/` is a byte-identical copy
> of the vendored source of record at `plugin/opencode-worktree/`; keep the two
> in sync. Its runtime deps are declared in `.opencode/package.json` and
> resolved from `.opencode/node_modules`, so **restart opencode** after any
> change.

## Repository layout

```
.
├── PLAN.md                    # Implementation plan + phase status
├── README.md                  # This file
├── AGENTS.md                  # Workspace notes (project facts, conventions)
├── opencode.json              # Config: constitution injection, orchestrator default, depth 2, permissions
├── RESEARCH-grok-build.md     # Research: grok-build harness (parallel tasks, worktrees)
├── issues/                    # Issue queue: todo / inprogress / review / completed
│   └── README.md              # Queue contract, naming, transitions, CLI
├── scripts/
│   └── issue_queue.py         # Deterministic, locked, no-clobber queue moves
├── tests/                     # Harness config + issue-queue tests (stdlib unittest)
├── plugin/
│   └── opencode-worktree/
│       ├── install.sh          # Full-harness or plugin-only installer
│       └── templates/
│           └── AGENTS.md       # Neutral workspace notes for new projects
├── .opencode/
│   ├── constitution.md        # Harness constitution (injected into every agent)
│   ├── agents/                # orchestrator, lead, planner, coder, reviewer, researcher
│   ├── commands/              # issues, feature, ship, status
│   ├── plugin/                # Installed worktree plugin (auto-loaded; copy of plugin/opencode-worktree/)
│   └── worktree.jsonc         # Worktree plugin config
├── sandbox/                   # Training project (Python + unittest) used to validate the harness
│   ├── AGENTS.md              # Sandbox-specific conventions (nested AGENTS.md test)
│   └── README.md              # Sandbox "product intent"
├── docs/
│   └── validation.md          # Scenario checklist + sign-off (scenarios 1–24)
└── .gitignore
```

> Git-ignored items not shown: `.opencode/package.json` + lockfile + `node_modules/`.
> The runtime package is intentionally per-project (see `PLAN.md` §5.2); the
> installer recreates it and runs the dependency install, so re-run it after a
> fresh clone. The worktree plugin needs its runtime deps (`jsonc-parser`, `zod`)
> installed there. `.opencode/.gitignore` itself is tracked/committable — it only
> ignores the generated artifacts.

## Quick start

1. Install opencode **1.18.2 or newer** — depth-2 delegation
   (`subagent_depth: 2`) needs it. Verified on 1.19.3 (Termux/Android); the
   plugin install was re-verified on 1.18.33, 2026-09-29.
2. Install the harness into a project from this checkout:

   ```bash
   ./plugin/opencode-worktree/install.sh /path/to/project
   ```

   This one command copies the constitution, agent team, commands, docs, and
   worktree plugin, and merges `opencode.json` without overriding existing
   keys (`default_agent` is never hijacked; `instructions` are unioned;
   permissions are filled only where missing, and harness bash rules are only
   added to an existing explicit `"*": "allow"` policy). Backups preserve file
   modes under `.opencode/.install-backups/`, and invalid config/package JSON
   stops the installer before any target write. Use `--plugin-only` to install
   just the worktree plugin, `--with-sandbox` to include the demo project, or
   `--force` to back up and replace template-owned files. **Restart opencode**
   afterward — config is loaded once at startup, so restart after any change to
   `opencode.json`, agents, commands, skills, or plugins.
3. Run the harness and sandbox tests to confirm the environment:

   ```bash
   python3 -m unittest discover -s tests
   python3 -m unittest discover -s sandbox
   ```

4. Try the issue queue: add `<NNN> <title>.md` under `issues/todo/`, then
   `/issues` (or `/issues all`). Success stops at `review`; accept explicitly
   with `/issues accept <id>`.
5. Or run a direct feature: `/feature Add a --version flag to the sandbox CLI,
   with tests.` Close out with `/ship` — then review the report (`Done /
   Verified / Decisions / Needs you`).

## Validation status

The harness is validated end-to-end against `sandbox/` — see
`docs/validation.md` for the full scenario checklist and sign-off table:

- **Scenarios 1–11 pass** (2026-08-15): inspect & understand, convention
  compliance, failure iteration, review pass, approval gate, docs update,
  delegation depth, worktree create/merge-back/GC on Termux.
- **Scenario 12** (constitution injection recitation) is applied and pending
  live verification after an opencode restart.
- **Scenarios 17–24** (depth-2 dispatch, numeric order +
  claim-before-dispatch, canonical issue branches, failure stays `inprogress`,
  review acceptance gate with merge-on-acceptance and rejection cleanup,
  parallel same-prefix groups) are configured and need a live session after an
  opencode restart.
- **Phase 5** (package as a copyable template) is the final phase; Phase 4.6's
  structural items remain pending.

## Docs

- `PLAN.md` — full implementation plan, decisions, phase status
- `issues/README.md` — issue queue contract, naming, transitions, CLI
- `docs/validation.md` — validation scenarios and sign-off
- `RESEARCH-grok-build.md` — research on grok-build's parallel-task/worktree
  design and what was adopted