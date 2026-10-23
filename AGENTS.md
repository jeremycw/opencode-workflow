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
- Issue queue: `issues/` (states `todo`, `inprogress`, `review`, `completed`);
  move issues only with `python3 scripts/issue_queue.py`, never by hand.
  `issues/README.md` documents the workflow; `/issues` drives it.
- Delegation hierarchy is depth 2 (`subagent_depth: 2`):
  `orchestrator` → `lead` → specialists. The orchestrator is the default
  primary; `/feature`, `/ship`, and `/status` start the `lead` directly.
- After changes to `opencode.json`, agent files, or commands: restart opencode
  (config is loaded once at startup).
