# Phase 4 + 4.5 + 4.7 — Sandbox Validation

Goal: prove the engineering loop end-to-end with zero risk before the workflow
is packaged as a copyable template (Phase 5 — no global promotion). All
scenarios run inside this repository against `sandbox/`.

Status legend: `pending` / `pass` / `fail` / `blocked` / `needs user` (verifiable only
in a live interactive session) / `pass (fallback)` (scenario met via the documented
fallback path).

## Environment (verified 2026-08-15; issue orchestration 2026-10-22; off-main queue 2026-10-23)

- opencode **1.19.3** on Termux (Android). Depth-2 delegation
  (`subagent_depth: 2`) requires **opencode >= 1.18.2**; the earlier 1.18.18
  runs below predate issue orchestration.
- Sandbox: Python `unittest`, stdlib only — `python3 -m unittest discover -s sandbox`
- No pytest installed; Node v18.20.4 available; only the installer config merge uses it
- Worktree plugin: **forked & adapted 2026-08-15 (Phase 4.5)** — originally an
  agent-centric copy at `~/.config/opencode/plugins/`; **as of 2026-09-29 installed
  project-scoped at `.opencode/plugin/`** (global copy superseded for this repo),
  byte-identical to `plugin/opencode-worktree/src/plugin/`, with deps
  `jsonc-parser@3.3.1` + `zod@4.1.8`; **no terminals are spawned** (work via bash +
  `worktree_apply`); repo config at `.opencode/worktree.jsonc`
- Plugin extended 2026-08-15 (gap-fix round): `worktree_delete` gained `deleteBranch`
  auto/always/never + `commitPending: false`; new `worktree_gc` tool (dry-run + `maxAgeDays`
  override, runGc reports pruned/unregistered/kept-with-reasons); `worktree_apply` gained
  `noFF`; `worktree_list` reconciles with git on every call (git-only worktrees shown as
  `(unregistered)`, expired flagged `*`); new `worktree_resolve_conflicts` (ours/theirs/abort)
- **Install verified 2026-09-29:** opencode 1.18.33 discovers
  `.opencode/plugin/worktree.ts` and registers all six `worktree_*` tools
  (`opencode debug info` / `opencode debug agent build`), no load errors. A live
  `worktree_create` round-trip is not part of this change.

## Scenario checklist

| # | Scenario | How to run | Expected | Status | Notes |
|---|---|---|---|---|---|
| 1 | Inspect & understand | Ask `lead`: "Summarize what this project does and its architecture." | Correct map of the harness + sandbox; conventions cited | pass | Independent `explore` map matched the lead's map (harness loop, agent team, commands, sandbox modules, both AGENTS.md convention sets cited) |
| 2 | Convention compliance | `/feature Add a --version flag to the sandbox CLI (sandbox/main.py), with tests.` | plan → implementation → green tests → commit → concise Done/Verified report; no approval prompts | pass | `--version` + `VERSION` + 3 CLI tests added; 15/15 green; README updated; committed `f70e93a`; no approval prompts raised |
| 3 | Failure iteration | `/feature Add caching to Thermostat.update so identical readings are not recomputed.` (README roadmap; tests assert decisions use the latest setpoint) | Harness hits red tests, debugs, and either fixes properly or reports the conflict. Never reports done with red tests | pass | coder ran naive memoization → red `test_decision_uses_latest_setpoint` → fixed with single-entry cache + `set_temperature` invalidation + `_decide` seam; 17/17 green; committed `076cc45` |
| 4 | Review pass | Inject a deliberate smell into `sandbox/` (e.g., a bare `except: pass` or unused import), then `/ship`. | `reviewer` flags it, `coder` fixes it | pass | Injected bare `except: pass` (sensor.py) + unused `import math` (display.py); reviewer flagged both (Critical/Should fix); coder reverted both + fixed EOF newline; 17/17 green; committed `9bf26f8` |
| 5 | Approval gate | After `/ship`, manually run `git push origin main` via bash; then push to a feature branch. | `ask` prompt on **all** pushes (main and feature branch), per decision PLAN.md §3.4 | pass | Verified by the user in a live session 2026-08-15: `ask` prompt confirmed on push. Config rules (`.opencode/opencode.json` + `lead.md`, last-match-wins ordering) verified present |
| 6 | Docs update | Change behavior (e.g., the Fahrenheit feature), then `/ship`. | README/doc updates land in the same work session | pass | README updated in the same session as each feature commit: `--version` usage (S2), caching roadmap removal (S3), Fahrenheit usage + roadmap removal (S7) |
| 7 | Delegation depth | `/feature Add Fahrenheit mode across display and thermostat.` (two-part feature) | `lead` delegates in parallel or serializes sensibly without user orchestration | pass | Full `planner` → `coder` → `reviewer` chain, serialized (shared working tree, interdependent halves, tiny repo). Reviewer caught `setpoint_in` duplicating the F formula in the domain layer; fixed by moving conversion to the display boundary + strict parser errors; 22/22 green; committed `dd09abb` |
| 8 | Worktree (Termux risk) | Trigger `worktree_create` for an independent task. | Worktree created and isolated work completes, then merges back (now via the forked plugin's `worktree_apply`) | pass | Plugin forked and adapted by the user 2026-08-15 (Phase 4.5): **no terminals are spawned** — worktree work happens via bash/`worktree_apply`, which removes the Termux terminal-detection failure entirely. See scenarios 9–11 |
| 9 | Worktree create on Termux | Trigger `worktree_create` for an independent task (forked plugin, no terminal). | Worktree created; isolated work completes via bash; no "No terminal emulator found" | pass | Verified 2026-08-15: `worktree_create` succeeded on Termux with zero terminal interaction; isolated commit made in the worktree and merged back (see S10) |
| 10 | Merge-back (`worktree_apply`) | Work in a worktree (change + commit), then `worktree_apply` with `merge`; introduce an overlapping edit to force a conflict. | Changes merge into main; conflicts reported as a file list; no data loss | pass | Verified 2026-08-15: `worktree_apply` (merge) applied the worktree branch to main, reported `docs/s10-conflict-probe.md` as conflicted (both sides preserved in conflict markers), `validation.md` merged cleanly; conflict resolved by dropping the scratch probe |
| 11 | Stale-worktree GC | Abandon a worktree (remove its git worktree manually), then trigger GC via a subsequent `worktree_create`. | Stale registry entry pruned automatically | pass | Verified 2026-08-15, **both paths**: (a) registry cleanup — `wt/gc-probe` removed via `git worktree remove`, then creating `wt/gc-trigger` ran GC before create and pruned the stale entry; (b) **age-based prune now tested in-session** via `worktree_gc(maxAgeDays: 0)` — dry-run flagged `wt/gc-age-probe2` as "expired and merged" (base branch recorded), run pruned its git worktree + registry entry; entry without a recorded base branch kept with reason (GC safety) |
| 12 | Constitution migration | After an opencode restart, ask `lead`, a subagent (`planner`), and a built-in (`explore`): "Recite the four sections of the Harness Constitution." Then read `AGENTS.md`. | All three recite the constitution **without reading any file** (proves `instructions` injection reaches primary, subagents, and built-ins); `AGENTS.md` contains zero constitution text (workspace notes only) | needs user | Migration applied 2026-08-15: constitution at `.opencode/constitution.md`, wired via `"instructions"` in `.opencode/opencode.json`; AGENTS.md trimmed to workspace notes. Injection verification requires a restarted session (config loads once at startup) |
| 17 | Depth-2 dispatch | Restart opencode, then `/issues` with one small `todo` issue. | `orchestrator` (primary, edit denied) claims the issue and dispatches exactly one `lead`; `lead` delegates to `explore`/`planner`/`coder`/`reviewer`; no "task denied" for the level-2 call | needs user | Requires `subagent_depth: 2` (opencode >= 1.18.2) and a restarted session; verify via transcript, not a live model test here |
| 18 | Numeric prefix groups + claim before dispatch | Put `002 Alpha.md`, `002 Beta.md`, and `010 Later.md` in `issues/todo/`, run `/issues all`. | Every `002` group member is claimed (`inprogress`) before any lead is spawned; `010` is not started while `002` is active; each issue stops at `review` | needs user | Requires a live session; deterministic queue behavior (group ordering, single-flight per prefix) is covered by `tests/test_issue_queue.py` |
| 19 | Failure stays inprogress | Dispatch an issue that the lead reports as `blocked` or `failed`. | Issue remains in `issues/inprogress/`; orchestrator reports the blocker and does not `finish` or `complete` it | needs user | Requires a live session; `return` is the only way back to `todo` |
| 20 | Acceptance gate | After a successful issue lands in `review`, try to proceed without `/issues accept <id>`. | Orchestrator never self-accepts; only explicit `/issues accept <id>` moves `review` → `completed`, and `/issues reject <id>` moves it back to `todo` | needs user | Requires a live session and the user's acceptance decision; with same-prefix siblings, accept/reject must use the exact filename (ambiguous numeric ids are rejected with the review filenames listed) |
| 21 | Parallel same-prefix group | Put `030 Alpha.md`, `030 Beta.md`, and `031 Later.md` in `issues/todo/`, run `/issues all`. | Both `030` issues are claimed before dispatch; one `lead` per issue runs in parallel worktrees; `031` is not started while `030` is active; each issue stops at `review` | needs user | Requires a live session; `next-group` and prefix-group claim mechanics are covered by `tests/test_issue_queue.py` |
| 22 | Canonical issue branch | Put one issue (e.g. `003 Use branches.md`) in `issues/todo/`, run `/issues`. | Orchestrator resolves `issue/003-use-branches` before claiming, passes it to the lead, and the lead creates/works/commits in that worktree; the lead does not apply, merge, or delete it; `finish` verifies the branch exists and is non-empty and moves the issue to `review` with main unchanged | needs user | Requires a live session; slug/branch resolution, any-state lookup, and duplicate-branch errors are covered deterministically by `tests/test_issue_queue.py` (`BranchTests`) |
| 23 | Finish does not merge (zero-commit guard) | Complete an issue whose branch has zero commits beyond the default branch (`git rev-list --count refs/heads/main..refs/heads/<branch>` = 0, e.g. its tip equals the default tip or main advanced since creation), or whose branch is missing, alongside a normal success. | The missing/zero-commit branch stays `inprogress` and is reported blocked; the normal success moves to `review`; `finish` never merges or deletes a worktree | needs user | Requires a live session; the guard is a prompt rule, not a queue-script rule |
| 24 | Squash acceptance, conflict resolution, and rejection cleanup | With an issue in `review`, run `/issues accept <id>` on a clean default branch; force a conflicting acceptance, then separately reject another issue (or `return` a blocked one). | Preflight: default branch clean outside `issues/` while the queue is still tracked (one-time migration), no merge in progress, no pre-existing `accept/<id>-<slug>` branch/worktree, canonical branch present; record `PRE_MERGE`; snapshot `issues/`. Create a temporary `accept/<id>-<slug>` worktree, run `git merge --squash issue/<id>-<slug>`, and create exactly one commit `issue <id>: <title>`. Conflicts: one fresh `lead` acceptance conflict resolver works only in that temporary worktree, preserves both intents, runs both suites + independent `reviewer`, and creates the single squash commit; main stays untouched. Verify `git rev-list --count PRE_MERGE..HEAD` = 1, `HEAD^ == PRE_MERGE`, clean status, both suites; fast-forward main with `git merge --ff-only accept/<id>-<slug>`; restore the queue snapshot; `git ls-files issues` empty and `/issues/` ignored; `complete` locally with no commit; delete the temporary acceptance worktree/branch and then the issue worktree/branch with `deleteBranch: "always"`. Failure before the fast-forward deletes the temporary worktree/branch and keeps `review` + the issue worktree/branch intact with main untouched; failure after the fast-forward is reported without reset. Reject/return: worktree+branch deleted (`always`, discarding WIP) before the local state move; an orphan branch blocks | needs user | Requires a live session and user acceptance. Issue 004 introduced the dispatched acceptance conflict resolver (historically in main); issue 005 supersedes the merge-on-main mechanics with squash acceptance in the temporary worktree, `--ff-only`, queue snapshot/restore, and a local `complete`. Resolution is delegated (orchestrator `edit` denied), one acceptance runs at a time, main is never reset, and agents never self-accept |
| 25 | Off-main local queue + one-commit squash | With a clean default branch, accept an issue whose canonical branch has at least two commits; then inspect the queue and `main`. | `issues/` is untracked and git-ignored (`git ls-files issues` empty, `git check-ignore` accepts it); all queue moves (`start`/`finish`/`complete`) happen with no `issues:` commit; accepting adds exactly one commit to main (`git rev-list --count PRE_MERGE..HEAD` = 1) whose message is `issue <id>: <title>` and whose squash contains every issue-branch change; the issue branch/worktree are deleted; existing historical `issues:` commits remain untouched (no history rewrite) | needs user | Requires a live session; the one-commit mechanics and queue-move-without-commit path are covered deterministically by `tests/test_acceptance_squash.py`, and default-root resolution from a linked worktree by the queue tests |
| 26 | One-time queue migration bootstrap | On a checkout where main still tracks `issues/`, accept the 005 migration branch using the documented bootstrap. | **New-prompt order (preferred, no extra queue commit):** `finish` is a local unstaged rename; preflight requires clean `git status --porcelain` outside `issues/` while `git ls-files issues` is non-empty, and no merge; record `PRE_MERGE`; snapshot the queue after the finish move (review state); create `accept/<id>-<slug>` from main HEAD; `git merge --squash issue/<id>-<slug>` deletes the old tracked queue path cleanly; create one commit `issue <id>: <title>`; verify exactly one commit above `PRE_MERGE`/`HEAD^`, clean accept worktree, both suites; verify main is still at `PRE_MERGE` and clean outside the allowed `issues/` local paths; `git merge --ff-only` without staging the queue move (accidental staging undone with `git restore --staged issues`); after the fast-forward the review file survives, `git ls-files issues` is empty, `/issues/` is ignored, and status is clean; refresh `README.md`/`.gitignore` from `plugin/opencode-worktree/templates/issues/`; `complete` locally with no commit; delete both worktrees/branches with `deleteBranch: "always"`. **Old committed-finish fallback:** if finish was already committed, `git merge --squash` conflicts on tracked queue paths; resolve in the accept worktree with `git rm -r --ignore-unmatch issues`, create the one commit, `--ff-only` deletes the tracked queue files; restore the queue from the snapshot taken at accept time (review state), refresh the template files, verify untracked/ignored, `complete` locally, delete both. An old session's attempt to stage and commit the queue files fails and is a no-op (never `git add -f`; local state is authoritative). The old merge-on-accept flow is not used | needs user | Requires a live session on a tracked-queue checkout. This is the migration path for issue 005; see the bootstrap warning below. The preferred order leaves no extra queue commit; the old fallback may retain a pre-accept management commit |

| 27 | Trimmed install footprint | Run the full installer from this checkout against a fresh temporary target, then inspect the installed paths and run `python3 .opencode/scripts/issue_queue.py status` there. | The target gains only runtime harness files under `.opencode/` (config, constitution, agents, commands, plugin, package manifest, dependency lockfile/`node_modules`, `.opencode/.gitignore`, `scripts/issue_queue.py`, `worktree.jsonc` when absent), the local `issues/` queue scaffolding, and the root `.gitignore` `/issues/` entry. It has **no** root `opencode.json`/`opencode.jsonc`, root `scripts/`, `docs/`, `AGENTS.md`, or `sandbox/`. `.opencode/opencode.json` carries the harness `default_agent`, `subagent_depth`, constitution instruction, and permissions; an existing target `.opencode/opencode.json` keeps its values (harness keys fill gaps only) and a root config is warned about but byte-identical. `--with-sandbox` adds only `sandbox/`; `--plugin-only` installs only the plugin + `.opencode/.gitignore`; `.opencode/opencode.jsonc` is rejected before writes; legacy root queue/docs/template-AGENTS files only warn and remain unchanged | pass | Implemented 2026-10-26 (issue 006); deterministic coverage in `tests/test_installer.py` (default footprint, runtime queue/config, sandbox, plugin-only, merge preservation, root warning, JSONC rejection, idempotency, legacy warnings, bad destination types) plus `tests/test_harness_config.py` path assertions |

**Correction (2026-08-15):** scenario 5's original "expected" text ("no prompt on the feature-branch push") contradicts locked decision PLAN.md §3.4: **ask on ALL `git push*`**, so a bare `git push` cannot bypass the gate. Expected behavior is an `ask` prompt on every push, feature branch included.

## Sign-off

**Rule: no file is packaged into the Phase 5 template until scenarios 1–7 pass** — all
Phase 4/4.5 scenarios 1–11 now pass (2026-08-15).

| Scenario | Status | Blocker / fix needed | Date |
|---|---|---|---|
| 1 Inspect & understand | pass | none | 2026-08-15 |
| 2 Convention compliance | pass | none | 2026-08-15 |
| 3 Failure iteration | pass | none | 2026-08-15 |
| 4 Review pass | pass | none | 2026-08-15 |
| 5 Approval gate | pass | user-verified live 2026-08-15 (ask prompt confirmed); config rules present | 2026-08-15 |
| 6 Docs update | pass | none | 2026-08-15 |
| 7 Delegation depth | pass | none | 2026-08-15 |
| 8 Worktree (Termux risk) | pass | plugin forked/adapted 2026-08-15 — no terminal spawn (Phase 4.5); see scenarios 9–11 | 2026-08-15 |
| 9 Worktree create on Termux | pass | none | 2026-08-15 |
| 10 Merge-back (worktree_apply) | pass | none | 2026-08-15 |
| 11 Stale-worktree GC | pass | both paths verified 2026-08-15: registry cleanup + age-based prune via `worktree_gc(maxAgeDays: 0)` | 2026-08-15 |
| 12 Constitution migration | needs user | applied 2026-08-15; injection verification requires a restarted opencode session (config loads once at startup) | 2026-08-15 |
| 17 Depth-2 dispatch | needs user | configured 2026-10-22; requires opencode restart + live `/issues` session | 2026-10-22 |
| 18 Numeric prefix groups + claim before dispatch | needs user | queue behavior (group ordering, claim-before-dispatch) covered by unit tests; live dispatch requires a restarted session | 2026-10-22 |
| 19 Failure stays inprogress | needs user | prompt/queue contract configured; requires a live blocked/failed lead report | 2026-10-22 |
| 20 Acceptance gate | needs user | orchestrator can only `finish`; `complete` is user-driven via `/issues accept`; exact filename required for same-prefix siblings | 2026-10-22 |
| 21 Parallel same-prefix group | needs user | `next-group` and per-prefix claim mechanics covered by unit tests; parallel worktree dispatch requires a restarted session + live model run | 2026-10-22 |
| 22 Canonical issue branch | needs user | branch/slug resolution and duplicate-branch errors covered by `BranchTests`; live dispatch requires a restarted session | 2026-10-23 |
| 23 Finish does not merge (zero-commit guard) | needs user | zero-commit guard is a prompt rule; requires a live lead report with `git rev-list --count main..branch` = 0 (no commit beyond the default branch) | 2026-10-23 |
| 24 Squash acceptance, conflict resolution, and rejection cleanup | needs user | temporary `accept/<id>-<slug>` worktree + `git merge --squash` + one commit; conflicts resolved by one resolver lead in that worktree + both suites + `reviewer`; one-commit/`HEAD^`/both-suite gates; `--ff-only`; queue snapshot/restore + local `complete`; delete both with `always`; failure before ff keeps `review` and main untouched, post-ff failure reports without reset (issue 005 supersedes issue 004 merge-on-main); rejection/return cleanup-before-move; requires live user acceptance | 2026-10-23 |
| 25 Off-main local queue + one-commit squash | needs user | `issues/` untracked/ignored, no queue commits, exactly one squash commit on main containing all issue changes, branches/worktrees deleted, historical `issues:` commits untouched; mechanics covered by `tests/test_acceptance_squash.py` and queue default-root tests | 2026-10-23 |
| 26 One-time queue migration bootstrap | needs user | preferred new-prompt order: local unstaged `finish` -> preflight clean outside `issues/` while tracked -> `PRE_MERGE` + snapshot after finish -> `accept/<id>-<slug>` squash commit -> `--ff-only` without staging the queue move -> restore/refresh template README/.gitignore -> `git ls-files issues` empty + ignored -> local `complete` no commit -> delete both `always`; committed-finish fallback uses `git rm -r --ignore-unmatch issues` in the accept worktree; an old session's queue-file stage/commit fails as a no-op (never `-f`); old merge-on-accept cannot finish 005 | 2026-10-23 |
| 27 Trimmed install footprint | pass | issue 006: full install writes only `.opencode/` runtime files + local `issues/` + root `.gitignore` `/issues/`; no target docs/AGENTS.md/root scripts/root config; config merge preserves target values; root config only warned about; `.opencode/opencode.jsonc` rejected; legacy files warned about and untouched; covered by `tests/test_installer.py` | 2026-10-26 |

**Sign-off: all scenarios 1–11 pass as of 2026-08-15. Scenario 12 (constitution
migration) is applied and pending live verification after an opencode restart.
Scenarios 17–26 (issue orchestration, Phase 4.7) are configured and marked
`needs user`: they require a restarted opencode session and a live model run.
Scenario 27 (trimmed install footprint, issue 006) passes deterministically
(2026-10-26).**
Phase 5 was re-scoped 2026-08-15: the goal is a **copyable template** (portability),
not global promotion — nothing is promoted to `~/.config/opencode/`.

**Deterministic coverage note (2026-10-23):** canonical branch resolution — the
slug rule, any-state lookup, numeric ambiguity, unknown ids, duplicate-branch
collisions, and the `branch` CLI's output/exit codes — is covered by
`BranchTests` in `tests/test_issue_queue.py`; the main-checkout default-root
resolution from a linked worktree and the `--root` override are covered by the
queue default-root tests. The no-merge `finish` and zero-commit guard are
prompt contracts verified live by scenarios 22–23. The issue 005 squash
acceptance mechanics (a two-commit issue branch squashed into exactly one
commit, `--ff-only`, and a queue state move with no commit) are covered by
`tests/test_acceptance_squash.py`, including the new `test_queue_migration_new_bootstrap_squashes_cleanly`
(preferred unstaged-finish order) and
`test_queue_migration_committed_finish_falls_back_to_squash`
(old committed-finish fallback) regression tests.
The issue 004 acceptance-conflict-resolution
history is preserved (resolver dispatch, both-suite and reviewer gates, one
acceptance at a time); issue 005 supersedes its merge-on-main mechanics with a
resolver working in the temporary acceptance worktree. That prompt contract
(resolver scope, snapshot/restore, one-commit/`HEAD^` gates, `--ff-only`,
failure cleanup) is covered structurally by `tests/test_harness_config.py`;
live model behavior remains `needs user`.

**Issue 005 bootstrap warning (one-time):** main currently tracks `issues/`. The
005 migration commit (`git rm -r --cached issues` + root-anchored `/issues/`,
which keeps `plugin/opencode-worktree/templates/issues/` tracked) makes a merge
or fast-forward remove the formerly tracked queue files from main's working
tree.

- **Preferred new-prompt order (no extra queue commit):** perform the local
  `finish` first as a plain unstaged rename. Preflight requires
  `git status --porcelain` clean outside `issues/` and no merge in progress;
  while `git ls-files issues` is non-empty (the one-time migration only),
  dirty paths under `issues/` are allowed and must not be staged or committed.
  Record `PRE_MERGE` and snapshot the queue **after** the finish move (review
  state), create `accept/<id>-<slug>` from main HEAD, and `git merge --squash`
  the migration branch: the deletion applies cleanly because main HEAD still has
  the old tracked queue path. Create one commit, verify it and both suites,
  fast-forward with `--ff-only` **without** staging the local queue move (an
  accidentally staged move is undone with `git restore --staged issues`), then
  refresh `README.md`/`.gitignore` from the template, verify the queue is
  untracked and ignored, and `complete` locally without committing.
- **Old committed-finish fallback:** if an old session already committed the
  finish, main is clean but has a tracked `issues/review/<file>` path that the
  migration branch does not delete, so `git merge --squash` conflicts on queue
  paths. Resolve in the accept worktree with `git rm -r --ignore-unmatch
  issues`, create the one commit, `--ff-only`, restore the queue from the
  snapshot taken at accept time, refresh the template files, and `complete`
  locally without committing.

An old session's attempt to stage and commit the queue files fails and is a
documented no-op — never `git add -f`; the local queue is authoritative. The
old merge-on-accept flow cannot safely finish 005; existing `issues:` commits
stay in history (no rewrite).

**Post-sign-off update (2026-09-29):** the worktree plugin was relocated into the
repo at `.opencode/plugin/` (project-scoped auto-discovery) so it travels with the
template. No scenario result changes.

**Issue 006 deterministic coverage (2026-10-26):** the trimmed install footprint
is covered by `tests/test_installer.py`, which runs the real installer against
temporary targets with stubbed dependency installs: default and `--with-sandbox`
footprints, plugin-only, `.opencode/opencode.json` merge preservation (including
`"*": "allow"` bash extension), root-config warning without modifying the root
file, `.opencode/opencode.jsonc` rejection before writes, idempotent re-runs,
legacy-file warnings (root `scripts/issue_queue.py`, `docs/validation.md`, old
template-marker `AGENTS.md`), and bad destination types failing before writes.
`tests/test_harness_config.py` asserts the repo has no root `opencode.json` or
root `scripts/issue_queue.py`, that the harness files live under `.opencode/`,
and that `templates/AGENTS.md` is gone. The queue tests install and import
`.opencode/scripts/issue_queue.py` and verify the new project-root depth for
linked worktrees, monorepo subdirectories, and non-git fallbacks.
