---
description: "Work the issue queue: status | next | all | accept <id> | reject <id>. Default is one issue per invocation, claimed before dispatch to a lead subagent and stopped at review for user acceptance."
agent: orchestrator
---

$ARGUMENTS

Interpret the arguments as one of:

- *empty* or `next` — claim the lowest-numbered `todo` issue with
  `python3 scripts/issue_queue.py start <id>` and dispatch one `lead` subagent
  for it. Move it to `inprogress` **before** dispatch. On `Outcome: success`,
  run `python3 scripts/issue_queue.py finish <id>` into `review`; on
  `blocked`/`failed`, leave it in `inprogress` and report the blocker.
- `status` — run `python3 scripts/issue_queue.py status` and report the queue
  (todo / inprogress / review / completed). Do not mutate anything.
- `all` — process `todo` issues sequentially in numeric order, one at a time,
  using the same claim-before-dispatch loop. Every issue still stops at
  `review`; never auto-accept and never skip the acceptance gate.
- `accept <id>` — the user has accepted a `review` issue; run
  `python3 scripts/issue_queue.py complete <id>`.
- `reject <id>` — return a `review` issue to `todo` with
  `python3 scripts/issue_queue.py reopen <id>` and report why.

One issue per invocation by default. Never implement, plan, or edit project
files yourself. Use `python3 scripts/issue_queue.py` for every state change;
do not move issue files by hand. Commit only issue-state moves (`git add
issues && git commit -m "issues: ..." -- issues`). Never push, and never mark
an issue complete without explicit user acceptance.
