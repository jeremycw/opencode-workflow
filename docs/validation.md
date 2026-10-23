# Phase 4 + 4.5 + 4.7 — Sandbox Validation

Goal: prove the engineering loop end-to-end with zero risk before the workflow
is packaged as a copyable template (Phase 5 — no global promotion). All
scenarios run inside this repository against `sandbox/`.

Status legend: `pending` / `pass` / `fail` / `blocked` / `needs user` (verifiable only
in a live interactive session) / `pass (fallback)` (scenario met via the documented
fallback path).

## Environment (verified 2026-08-15; issue orchestration 2026-10-22)

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
| 5 | Approval gate | After `/ship`, manually run `git push origin main` via bash; then push to a feature branch. | `ask` prompt on **all** pushes (main and feature branch), per decision PLAN.md §3.4 | pass | Verified by the user in a live session 2026-08-15: `ask` prompt confirmed on push. Config rules (`opencode.json` + `lead.md`, last-match-wins ordering) verified present |
| 6 | Docs update | Change behavior (e.g., the Fahrenheit feature), then `/ship`. | README/doc updates land in the same work session | pass | README updated in the same session as each feature commit: `--version` usage (S2), caching roadmap removal (S3), Fahrenheit usage + roadmap removal (S7) |
| 7 | Delegation depth | `/feature Add Fahrenheit mode across display and thermostat.` (two-part feature) | `lead` delegates in parallel or serializes sensibly without user orchestration | pass | Full `planner` → `coder` → `reviewer` chain, serialized (shared working tree, interdependent halves, tiny repo). Reviewer caught `setpoint_in` duplicating the F formula in the domain layer; fixed by moving conversion to the display boundary + strict parser errors; 22/22 green; committed `dd09abb` |
| 8 | Worktree (Termux risk) | Trigger `worktree_create` for an independent task. | Worktree created and isolated work completes, then merges back (now via the forked plugin's `worktree_apply`) | pass | Plugin forked and adapted by the user 2026-08-15 (Phase 4.5): **no terminals are spawned** — worktree work happens via bash/`worktree_apply`, which removes the Termux terminal-detection failure entirely. See scenarios 9–11 |
| 9 | Worktree create on Termux | Trigger `worktree_create` for an independent task (forked plugin, no terminal). | Worktree created; isolated work completes via bash; no "No terminal emulator found" | pass | Verified 2026-08-15: `worktree_create` succeeded on Termux with zero terminal interaction; isolated commit made in the worktree and merged back (see S10) |
| 10 | Merge-back (`worktree_apply`) | Work in a worktree (change + commit), then `worktree_apply` with `merge`; introduce an overlapping edit to force a conflict. | Changes merge into main; conflicts reported as a file list; no data loss | pass | Verified 2026-08-15: `worktree_apply` (merge) applied the worktree branch to main, reported `docs/s10-conflict-probe.md` as conflicted (both sides preserved in conflict markers), `validation.md` merged cleanly; conflict resolved by dropping the scratch probe |
| 11 | Stale-worktree GC | Abandon a worktree (remove its git worktree manually), then trigger GC via a subsequent `worktree_create`. | Stale registry entry pruned automatically | pass | Verified 2026-08-15, **both paths**: (a) registry cleanup — `wt/gc-probe` removed via `git worktree remove`, then creating `wt/gc-trigger` ran GC before create and pruned the stale entry; (b) **age-based prune now tested in-session** via `worktree_gc(maxAgeDays: 0)` — dry-run flagged `wt/gc-age-probe2` as "expired and merged" (base branch recorded), run pruned its git worktree + registry entry; entry without a recorded base branch kept with reason (GC safety) |
| 12 | Constitution migration | After an opencode restart, ask `lead`, a subagent (`planner`), and a built-in (`explore`): "Recite the four sections of the Harness Constitution." Then read `AGENTS.md`. | All three recite the constitution **without reading any file** (proves `instructions` injection reaches primary, subagents, and built-ins); `AGENTS.md` contains zero constitution text (workspace notes only) | needs user | Migration applied 2026-08-15: constitution at `.opencode/constitution.md`, wired via `"instructions"` in `opencode.json`; AGENTS.md trimmed to workspace notes. Injection verification requires a restarted session (config loads once at startup) |
| 17 | Depth-2 dispatch | Restart opencode, then `/issues` with one small `todo` issue. | `orchestrator` (primary, edit denied) claims the issue and dispatches exactly one `lead`; `lead` delegates to `explore`/`planner`/`coder`/`reviewer`; no "task denied" for the level-2 call | needs user | Requires `subagent_depth: 2` (opencode >= 1.18.2) and a restarted session; verify via transcript, not a live model test here |
| 18 | Numeric prefix groups + claim before dispatch | Put `002 Alpha.md`, `002 Beta.md`, and `010 Later.md` in `issues/todo/`, run `/issues all`. | Every `002` group member is claimed (`inprogress`) before any lead is spawned; `010` is not started while `002` is active; each issue stops at `review` | needs user | Requires a live session; deterministic queue behavior (group ordering, single-flight per prefix) is covered by `tests/test_issue_queue.py` |
| 19 | Failure stays inprogress | Dispatch an issue that the lead reports as `blocked` or `failed`. | Issue remains in `issues/inprogress/`; orchestrator reports the blocker and does not `finish` or `complete` it | needs user | Requires a live session; `return` is the only way back to `todo` |
| 20 | Acceptance gate | After a successful issue lands in `review`, try to proceed without `/issues accept <id>`. | Orchestrator never self-accepts; only explicit `/issues accept <id>` moves `review` → `completed`, and `/issues reject <id>` moves it back to `todo` | needs user | Requires a live session and the user's acceptance decision; with same-prefix siblings, accept/reject must use the exact filename (ambiguous numeric ids are rejected with the review filenames listed) |
| 21 | Parallel same-prefix group | Put `030 Alpha.md`, `030 Beta.md`, and `031 Later.md` in `issues/todo/`, run `/issues all`. | Both `030` issues are claimed before dispatch; one `lead` per issue runs in parallel worktrees; `031` is not started while `030` is active; each issue stops at `review` | needs user | Requires a live session; `next-group` and prefix-group claim mechanics are covered by `tests/test_issue_queue.py` |
| 22 | Canonical issue branch | Put one issue (e.g. `003 Use branches.md`) in `issues/todo/`, run `/issues`. | Orchestrator resolves `issue/003-use-branches` before claiming, passes it to the lead, and the lead creates/works/commits in that worktree; the lead does not apply, merge, or delete it; `finish` verifies the branch exists and is non-empty and moves the issue to `review` with main unchanged | needs user | Requires a live session; slug/branch resolution, any-state lookup, and duplicate-branch errors are covered deterministically by `tests/test_issue_queue.py` (`BranchTests`) |
| 23 | Finish does not merge (zero-commit guard) | Complete an issue whose branch has zero commits beyond the default branch (`git rev-list --count refs/heads/main..refs/heads/<branch>` = 0, e.g. its tip equals the default tip or main advanced since creation), or whose branch is missing, alongside a normal success. | The missing/zero-commit branch stays `inprogress` and is reported blocked; the normal success moves to `review`; `finish` never merges or deletes a worktree | needs user | Requires a live session; the guard is a prompt rule, not a queue-script rule |
| 24 | Acceptance merge and rejection cleanup | With an issue in `review`, run `/issues accept <id>` on a clean default branch; separately reject another issue (or `return` a blocked one). | Accept: preflight clean main -> `worktree_apply` merge -> both suites green -> `completed` -> merged worktree/branch deleted; a conflict or red suite keeps `review` and the worktree. Reject/return: worktree+branch deleted (`always`, discarding WIP) before the state move; an orphan branch blocks | needs user | Requires a live session and user acceptance; orchestrator never resolves conflicts, resets main, or self-accepts |

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
| 24 Acceptance merge and rejection cleanup | needs user | configured for `worktree_apply` merge + both suites + `worktree_delete auto`; rejection/return cleanup-before-move; requires live user acceptance | 2026-10-23 |

**Sign-off: all scenarios 1–11 pass as of 2026-08-15. Scenario 12 (constitution
migration) is applied and pending live verification after an opencode restart.
Scenarios 17–24 (issue orchestration, Phase 4.7) are configured and marked
`needs user`: they require a restarted opencode session and a live model run.**
Phase 5 was re-scoped 2026-08-15: the goal is a **copyable template** (portability),
not global promotion — nothing is promoted to `~/.config/opencode/`.

**Deterministic coverage note (2026-10-23):** canonical branch resolution — the
slug rule, any-state lookup, numeric ambiguity, unknown ids, duplicate-branch
collisions, and the `branch` CLI's output/exit codes — is covered by
`BranchTests` in `tests/test_issue_queue.py`. The no-merge `finish`, zero-commit
guard, acceptance merge, and rejection/orphan cleanup are prompt contracts
verified live by scenarios 22–24.

**Post-sign-off update (2026-09-29):** the worktree plugin was relocated into the
repo at `.opencode/plugin/` (project-scoped auto-discovery) so it travels with the
template. No scenario result changes.