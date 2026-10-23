# opencode-worktree

> Agent-centric git worktrees for opencode. Create, merge, and clean up isolated worktrees — no terminals spawned, no session forking.

An [OpenCode](https://github.com/sst/opencode) plugin that gives agents first-class git worktree isolation:

- **`worktree_create`** — spin up an isolated worktree on a new branch
- **`worktree_apply`** — merge the worktree's changes back into the main checkout, with conflict reporting
- **`worktree_delete`** — commit a snapshot and remove the worktree (branch cleanup included)
- **`worktree_list`** — see all worktrees, their age, and merge status (reconciled with git)
- **`worktree_gc`** — prune stale worktrees, with a `dryRun` preview
- **`worktree_resolve_conflicts`** — resolve a pending merge as ours/theirs, or abort it

Forked from [kdcokenny/opencode-worktree](https://github.com/kdcokenny/opencode-worktree) with the terminal-spawning machinery (tmux/cmux/platform terminals, session forking, OCX launch context) removed. This fork is **agent-centric**: the agent itself works inside the worktree via the `bash` tool or delegated subagents, then merges back.

## Why This Exists

Isolated work for AI agents is the core of a parallel-delegation workflow. The upstream plugin was built for *humans*: it opened a new terminal with OpenCode running in the worktree. That doesn't fit agentic flows — and on headless/limited environments (like Termux) spawning terminals fails outright.

This version is the other side of that loop: the agent creates a worktree, does isolated work in it, and merges the result back with a conflict summary. It mirrors the `ApplyMode::Overwrite / Merge` semantics of grok-build's `workspace.apply_worktree` (see `RESEARCH-grok-build.md`).

## How It Works

```text
lead agent                      main checkout
    │  worktree_create(branch)        │
    ▼                                 │
worktree on feature/x  ◄── isolated work via bash/task
    │  worktree_apply(branch, merge)  │
    └──────────►  git merge → conflicts reported as file list
    │  worktree_delete(branch)        │
    └──────────►  snapshot commit + git worktree remove
```

1. **Create** — `worktree_create(branch: "feature/x")` creates the worktree, syncs configured files, runs `postCreate` hooks, and registers it in a SQLite registry.
2. **Work** — the agent uses the `bash` tool with `workdir=<path>` (or a delegated subagent with that cwd). No terminal is spawned.
3. **Apply** — `worktree_apply(branch: "feature/x", mode: "merge")`:
   - commits any uncommitted worktree changes as a snapshot (`commitPending: false` to skip)
   - runs `git merge` in the main checkout
   - reports merged commits, changed files, and any conflicts as a file list (left for resolution)
   - `mode: "overwrite"` resolves all conflicts in favor of the worktree branch
   - `noFF: true` forces a merge commit (`--no-ff`) instead of a linear fast-forward, preserving the branch topology as a merge record
   - `deleteAfter: true` removes the worktree after a clean merge
4. **Cleanup** — `worktree_delete(branch, ...)` commits a snapshot, removes the worktree, and deletes the branch when safe; `worktree_gc()` prunes stale worktrees.

Worktrees are stored in `~/.local/share/opencode/worktree/<project-id>/<branch>/` outside your repository.

## Tools

| Tool | Purpose |
|------|---------|
| `worktree_create(branch, baseBranch?)` | Create an isolated git worktree. Returns the worktree path to work in. |
| `worktree_apply(branch, mode?, commitPending?, deleteAfter?, noFF?)` | Merge the worktree branch into the main checkout. `merge` (default) surfaces conflicts as a file list; `overwrite` lets the worktree win; `noFF: true` preserves topology with a merge commit. |
| `worktree_delete(branch, deleteBranch?, commitPending?, reason?)` | Commit a snapshot and remove the worktree. `deleteBranch` controls branch cleanup: `auto` (default) deletes the branch only if merged into its base, `always` force-deletes (`-D`), `never` keeps it. `commitPending: false` discards uncommitted changes instead of snapshotting them. |
| `worktree_list()` | List worktrees (reconciled with `git worktree list`) with path, age, merge status, and an `*` marker for entries past `gc.maxAgeDays`. Git-only worktrees are shown as `(unregistered)`. |
| `worktree_gc(dryRun?, maxAgeDays?)` | Prune stale worktrees: unregister entries whose git worktree is gone, remove expired-and-merged ones. `dryRun: true` previews without changing anything; `maxAgeDays` overrides the configured threshold. |
| `worktree_resolve_conflicts(strategy)` | Resolve a pending merge in the main checkout: `ours`/`theirs` resolves every conflicted file in favor of that side and stages it (finish with `git commit`); `abort` cancels the merge. |

### Usage examples

```yaml
worktree_create:
  branch: "feature/dark-mode"
  baseBranch: "main"
```

```yaml
worktree_apply:
  branch: "feature/dark-mode"
  mode: "merge"
  deleteAfter: true
  noFF: true  # keep a merge commit instead of linearizing
```

```yaml
worktree_delete:
  branch: "feature/dark-mode"
  deleteBranch: "auto"  # deletes the branch since it's merged
  reason: "Feature complete, merged to main"
```

```yaml
worktree_gc:
  dryRun: true  # preview what would be pruned
```

```yaml
worktree_resolve_conflicts:
  strategy: "theirs"  # or "ours"; "abort" cancels the pending merge
```

## Installation

Run the installer from a harness checkout against your project:

```bash
./plugin/opencode-worktree/install.sh /path/to/your/project
```

`TARGET_PROJECT_DIR` defaults to the current directory. The installer is
non-interactive and idempotent. Issue orchestration needs opencode **>= 1.18.2**
for `subagent_depth: 2`; the installer sets it when absent and warns without
overriding a lower target value.

### Modes and options

| Mode / option | Effect |
|---|---|
| *(default)* | Installs the **full harness** when run from a harness checkout; otherwise falls back to plugin-only with a notice. |
| `--plugin-only` | Installs only the worktree plugin (the old installer behavior). |
| `--with-sandbox` | Also installs the sandbox demo project. Implies full harness; errors if no harness checkout is found. |
| `--force` | Backs up and replaces an existing `AGENTS.md`, `.opencode/worktree.jsonc`, or `sandbox/`. A no-op in plugin-only mode. |
| `-h`, `--help` | Show usage. |
| `--` | End of options. |

Both modes ensure `.opencode/.gitignore` ignores `node_modules`, `package.json`,
the lockfiles, and `.install-backups`, so a plugin-only install does not leave
npm artifacts untracked.

### What full mode installs

- `opencode.json` — merged into any existing config (see guarantees below)
- `.opencode/constitution.md`
- `.opencode/agents/{orchestrator,lead,planner,coder,reviewer,researcher}.md`
- `.opencode/commands/{issues,feature,ship,status}.md`
- `.opencode/worktree.jsonc` — skipped if one already exists
- `AGENTS.md` from `templates/AGENTS.md` — skipped if one already exists
- `docs/validation.md`
- `scripts/issue_queue.py` — the locked, no-clobber issue queue helper
- `issues/README.md`, `issues/.gitignore`, and
  `issues/{todo,inprogress,review,completed}/.gitkeep` — scaffolding only;
  existing project issue files/docs are kept unless `--force` (which backs up
  and replaces)
- `src/plugin/` → `.opencode/plugin/` (per file; unrelated plugins are kept)
- `.opencode/.gitignore` (created or appended with missing entries; it ignores
  `node_modules`, `package.json`, `package-lock.json`, `bun.lock`, and
  `.install-backups`, but not itself)
- runtime deps in `.opencode/package.json`, installed with `bun install`
  (falling back to `npm install`)

The runtime `package.json` is intentionally per-project and git-ignored: it
declares the dependency versions resolved for this checkout. Re-running the
installer after a fresh clone recreates it and runs the dependency install.

With `--with-sandbox`, the nine files in `sandbox/` are copied too (never
`__pycache__` or `*.pyc`). An existing `sandbox/` is skipped unless `--force`
is given; with `--force` it is always backed up, removed, and recopied so stale
generated files cannot survive.

Full mode never copies `PLAN.md`, the root `README.md`/`TODO.md`/research
notes, the root `.gitignore`, `.git`, `node_modules`, lockfiles, the harness's
own installed `.opencode/plugin/`, or the plugin package's development files
(`README`, `LICENSE`, `tsconfig`, `package.json`, `install.sh`, its local
`.opencode/worktree.jsonc`).

### Config merge guarantees

`opencode.json` is merged with **existing keys winning**:

- Keys already in the target are kept, including unknown custom keys.
- `default_agent` is never hijacked: it is set to the harness default
  (`orchestrator`) only when absent; an existing target value (including
  `lead`) is preserved.
- `subagent_depth` is copied (`2`) only when absent. An existing value is
  preserved; if it is below `2`, the installer **warns** that depth-2 issue
  orchestration needs `subagent_depth: 2` and `opencode >= 1.18.2`, but it does
  not override the target.
- `instructions` is unioned: `.opencode/constitution.md` is appended if the
  target already has an array, or the harness array is copied if absent.
- `permission` is filled in only where keys are missing. Existing objects such
  as `external_directory` are deep-merged with target values winning.
- An existing `permission.bash` is never relaxed: harness bash rules are added
  **only** when the target already has an explicit `"*": "allow"` policy. If
  `"*"` is missing, `"deny"`, `"ask"`, or any non-string value, no harness bash
  rules are added and the installer warns why. `"*": "allow"` itself is never
  injected into an existing policy.
- If the target has a `permission` object but no `bash` key, the bash policy is
  left untouched and the installer warns that the harness bash safety rules were
  not added. Other missing permission keys (such as webfetch, websearch, and
  worktree rules) are still added. A bash block is copied wholesale only when
  the target has no `permission` object at all.
- No write happens when the merged result is semantically unchanged, so target
  formatting is preserved for no-ops.
- Invalid target JSON is backed up and the installer stops before any other
  target write: `opencode.json` (full mode) and `.opencode/package.json` (both
  modes), including non-object documents. An empty or whitespace-only
  `.opencode/package.json` is accepted and populated with the runtime
  dependencies; non-empty invalid JSON still stops the run. A target
  `opencode.jsonc` is rejected (exit 1) rather than guessed at — merge it
  manually or use `--plugin-only`.

Dependency specs already present in `.opencode/package.json` are preserved; the
installer keeps them and prints a note instead of overwriting. `@opencode-ai/sdk`
is type-only and intentionally not installed (it is bundled with opencode).

### Backups

Files that would change (including `.opencode/.gitignore` when entries are
appended) are backed up first to:

```text
.opencode/.install-backups/<YYYYmmddHHMMSS>-<pid>/<relative-path>
```

`.install-backups` is added to `.opencode/.gitignore`. The backup directory and
its timestamped root are created with mode `0700`, and each backup preserves
the source file's mode (for example a `0600` `opencode.json` stays `0600`).
Identical files are not backed up, and no `*.bak` files are written into
loader-scanned directories such as `.opencode/agents/`, `.opencode/commands/`,
or `.opencode/plugin/`.

### After install

Restart opencode — configuration, agents, commands, and plugins are loaded once
at startup. The worktree plugin also needs the Bun runtime (`bun:sqlite`) at
execution time even though dependencies may have been installed with npm. The
installer updates managed directories in place; files removed from a newer
harness version are not deleted from the target.

**Requirements:**
- `bun` (for `bun:sqlite` and the Bun runtime APIs used by the plugin)
- `jsonc-parser` and `zod` available to the plugin loader (`bun add jsonc-parser zod` inside the plugin directory, or symlink from a shared location)
- `@opencode-ai/plugin` and `@opencode-ai/sdk` (bundled with opencode; pinned via `package.json` for typechecking)

## Configuration

Auto-creates `.opencode/worktree.jsonc` on first use:

```jsonc
{
  "worktreePath": "~/my-worktrees", // optional custom storage base

  "sync": {
    "copyFiles": [".env", ".env.local"], // copied into new worktrees
    "symlinkDirs": ["node_modules"],     // symlinked (saves disk space)
    "exclude": []
  },

  "hooks": {
    "postCreate": ["pnpm install"],      // run after creation
    "preDelete": ["docker compose down"] // run before deletion
  },

  "gc": {
    "enabled": true,        // automatic stale-worktree pruning
    "maxAgeDays": 30,       // prune worktrees older than this
    "onlyIfMerged": true    // only prune branches merged into their base
  }
}
```

## GC (stale-worktree cleanup)

Runs on plugin load, before each `worktree_create`, and on `session.idle` — and on demand via `worktree_gc`:

1. Unregisters entries whose git worktree no longer exists (removed manually).
2. Removes worktrees older than `maxAgeDays` whose branch is merged into its base branch (safe by default — `onlyIfMerged: false` disables the guard).

`worktree_gc(dryRun: true)` lists exactly what would be pruned without touching anything, and `worktree_gc(maxAgeDays: N)` overrides the configured threshold — useful for exercising the age-based path in-session without aging the database. `worktree_list` also reconciles the registry with git on every call, so manual `git worktree remove` never leaves a stale entry visible.

## Suggested workflow (agentic harness)

Pair with a two-level hierarchy: `orchestrator` (primary) owns `issues/` and
works numeric prefix groups, dispatching one `lead` per issue with every member
of the active group running in parallel; `lead` (mode `all`) delegates to
worktrees in parallel; specialists never delegate.

- `/issues` claims every `todo` issue in the current same-prefix group
  (`todo` → `inprogress`) **before** spawning one `lead` per issue, each in its
  own worktree on the canonical branch `issue/<zero-padded id>-<slug>`
  (`issues/README.md` has the slug rule). The issue lead works and commits
  inside that worktree but does **not** call `worktree_apply`, does not merge
  to the default branch, and does not delete the worktree. Success lands in
  `review` with branch and worktree intact for explicit **user** acceptance;
  the orchestrator then applies it on acceptance (`worktree_apply` in `merge`
  mode, both suites green, `complete`, then `worktree_delete` with
  `deleteBranch: "auto"`). Failure stays `inprogress` with the worktree intact.
- Direct-mode independent tasks (`/feature`-style) are **unchanged**:
  `worktree_create` each, then `worktree_apply(branch, mode: "merge")` back
  before the final report and `worktree_delete` after verification. Only an
  issue-dispatched `lead` defers apply/merge/delete to the orchestrator's
  acceptance gate.
- Delegation depth is 2 (`subagent_depth: 2`): the orchestrator may task
  `lead`; `lead` may task planners/coders/reviewers; specialists never spawn
  subagents.
- If an apply surfaces conflicts, resolve them with `worktree_resolve_conflicts(strategy: "ours"/"theirs")` and finish with `git commit`, or abort and re-plan.

## Security

- Branch names validated against git ref rules and shell metacharacters.
- File sync paths validated against directory traversal and symlink escapes.
- All git commands run via `Bun.spawn` with argument arrays — no shell interpolation.
- GC only removes merged, expired worktrees (configurable).

## License

MIT. Forked from [kdcokenny/opencode-worktree](https://github.com/kdcokenny/opencode-worktree), originally inspired by [opencode-worktree-session](https://github.com/felixAnhalt/opencode-worktree-session) by Felix Anhalt.