# Workspace Notes

This repository is the engineering-harness project: a staging ground for a
copyable opencode template (see PLAN.md). The `sandbox/` directory is a small
training project used to validate the harness (its own conventions live in
`sandbox/AGENTS.md`).

## Project facts

- Tests: `python3 -m unittest discover -s tests` (harness config + issue queue)
  and `python3 -m unittest discover -s sandbox` (training project). Both use
  stdlib `unittest`; pytest is not installed on this Termux box.
- Plan and status: `PLAN.md`, `docs/validation.md`
- Issue queue: `issues/` is a **local, git-ignored, untracked** queue shared by
  all worktrees (states `todo`, `inprogress`, `review`, `completed`); move
  issues only with `python3 .opencode/scripts/issue_queue.py`, never by hand,
  and never commit queue moves. The canonical queue docs/scaffolding live at
  `plugin/opencode-worktree/templates/issues/`; the full installer copies them.
  Acceptance is one squash commit staged in a temporary
  `accept/<id>-<slug>` worktree, then fast-forwarded to main. Preflight is
  clean outside `issues/` while the queue is still tracked (one-time
  migration); the bootstrap performs the local `finish` first and snapshots the
  queue after it, with a committed-finish fallback for an old session.
  `/issues` drives the workflow.
- Delegation hierarchy is depth 2 (`subagent_depth: 2`):
  `orchestrator` → `lead` → specialists. The orchestrator is the default
  primary; `/feature`, `/ship`, and `/status` start the `lead` directly.
- After changes to `.opencode/opencode.json`, agent files, or commands:
  restart opencode (config is loaded once at startup).
