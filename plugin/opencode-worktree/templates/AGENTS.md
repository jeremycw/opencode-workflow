# Workspace Notes

> Project-specific facts and conventions for agents working in this repository.
> The behavioral contract lives in `.opencode/constitution.md`; this file only
> records what is unique to this workspace.

## Project facts

- **Stack:** <languages, frameworks, runtime versions>
- **Tests:** <command, e.g. `npm test` or `python3 -m unittest discover -s tests`>
- **Lint:** <command, or "none">
- **Build:** <command, or "none">

## Conventions

- <Project-specific style rules, module boundaries, and invariants>
- <How to run a focused test, where new code belongs, what not to touch>
- <Anything agents must know before changing this codebase>

## Configuration changes

- opencode loads `opencode.json`, agents, commands, and plugins once at
  startup. Restart opencode after changing any of them.
