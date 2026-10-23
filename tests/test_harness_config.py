"""Structural tests for the opencode harness configuration.

These check the invariants that make issue orchestration and depth-2 dispatch
work: the orchestrator is the default primary, the lead can be a subagent, the
specialists cannot delegate, and the installer/docs/scaffolding travel with the
harness. They intentionally avoid live model sessions.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from _frontmatter import load_frontmatter

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / ".opencode" / "agents"
COMMANDS = ROOT / ".opencode" / "commands"


def agent(name: str) -> dict:
    return load_frontmatter(AGENTS / f"{name}.md")


def command(name: str) -> tuple[dict, str]:
    path = COMMANDS / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    return load_frontmatter(path), text


class ConfigTests(unittest.TestCase):
    def test_default_agent_and_subagent_depth(self):
        config = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
        self.assertEqual(config["default_agent"], "orchestrator")
        self.assertEqual(config["subagent_depth"], 2)
        self.assertIn(".opencode/constitution.md", config["instructions"])

    def test_orchestrator_is_primary_editless_and_dispatches_only_lead(self):
        front = agent("orchestrator")
        self.assertEqual(front["mode"], "primary")
        self.assertEqual(front["permission"]["edit"], "deny")
        self.assertEqual(front["permission"]["todowrite"], "allow")
        self.assertEqual(front["permission"]["task"], {"*": "deny", "lead": "allow"})

    def test_orchestrator_keeps_bash_approval_gates(self):
        bash = agent("orchestrator")["permission"]["bash"]
        self.assertEqual(bash["*"], "allow")
        for pattern in (
            "git push*",
            "git reset --hard*",
            "git branch -D*",
            "git clean -f*",
            "git push --force*",
            "rm -rf*",
            "npm publish*",
            "*issue_queue.py complete*",
            "*issue_queue.py reopen*",
        ):
            self.assertEqual(bash.get(pattern), "ask", pattern)
        keys = list(bash)
        for pattern in ("*issue_queue.py complete*", "*issue_queue.py reopen*"):
            self.assertGreater(keys.index(pattern), keys.index("*"), pattern)

    def test_lead_is_all_mode_and_can_todo_when_subagent(self):
        front = agent("lead")
        self.assertEqual(front["mode"], "all")
        self.assertEqual(front["permission"]["todowrite"], "allow")
        task = front["permission"]["task"]
        self.assertEqual(task["*"], "deny")
        for target in ("planner", "coder", "reviewer", "researcher", "explore"):
            self.assertEqual(task.get(target), "allow", target)

    def test_lead_keeps_bash_approval_gates(self):
        bash = agent("lead")["permission"]["bash"]
        self.assertEqual(bash["*"], "allow")
        for pattern in (
            "git push*",
            "git reset --hard*",
            "git branch -D*",
            "git clean -f*",
            "git push --force*",
            "rm -rf*",
        ):
            self.assertEqual(bash.get(pattern), "ask", pattern)

    def test_specialists_are_subagents_without_task_rules(self):
        for name in ("planner", "coder", "reviewer", "researcher"):
            with self.subTest(agent=name):
                front = agent(name)
                self.assertEqual(front["mode"], "subagent")
                self.assertNotIn("task", front["permission"])

    def test_commands_route_to_the_right_agent(self):
        issues_front, issues_text = command("issues")
        self.assertEqual(issues_front["agent"], "orchestrator")
        for expected in ("start", "finish", "complete", "reopen", "accept", "reject"):
            self.assertIn(expected, issues_text)

        for name in ("feature", "ship", "status"):
            with self.subTest(command=name):
                front, text = command(name)
                self.assertEqual(front["agent"], "lead")
        _, status_text = command("status")
        self.assertIn("issue_queue.py status", status_text)

    def test_installer_ships_orchestrator_issues_and_queue_script(self):
        installer = (ROOT / "plugin" / "opencode-worktree" / "install.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "AGENT_FILES=(orchestrator lead planner coder reviewer researcher)", installer
        )
        self.assertIn("COMMAND_FILES=(issues feature ship status)", installer)
        self.assertIn("ISSUE_STATES=(todo inprogress review completed)", installer)
        for token in (
            "scripts/issue_queue.py",
            "issues/README.md",
            "issues/.gitignore",
            ".gitkeep",
        ):
            self.assertIn(token, installer)

    def test_issue_scaffolding_exists(self):
        issues = ROOT / "issues"
        for state in ("todo", "inprogress", "review", "completed"):
            with self.subTest(state=state):
                self.assertTrue((issues / state).is_dir())
                self.assertTrue((issues / state / ".gitkeep").is_file())
        self.assertTrue((issues / "README.md").is_file())
        self.assertIn(".lock", (issues / ".gitignore").read_text(encoding="utf-8"))

    def test_docs_mention_issue_orchestration(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for token in ("orchestrator", "subagent_depth", "/issues", "issue_queue.py", "1.18.2"):
            self.assertIn(token, readme)

        constitution = (ROOT / ".opencode" / "constitution.md").read_text(encoding="utf-8")
        for token in ("orchestrator", "single-flight", "issue orchestration"):
            self.assertLowerIn(token.lower(), constitution.lower())

        agents_notes = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("python3 -m unittest discover -s tests", agents_notes)
        self.assertIn("issues/", agents_notes)
        self.assertIn("subagent_depth", agents_notes)

        validation = (ROOT / "docs" / "validation.md").read_text(encoding="utf-8")
        for token in ("1.19.3", "1.18.2", "Depth-2 dispatch", "Acceptance gate"):
            self.assertIn(token, validation)

        plan = (ROOT / "PLAN.md").read_text(encoding="utf-8")
        for token in ("Phase 4.7", "subagent_depth"):
            self.assertIn(token, plan)

        plugin_readme = (ROOT / "plugin" / "opencode-worktree" / "README.md").read_text(
            encoding="utf-8"
        )
        for token in ("orchestrator", "issues/", "subagent_depth"):
            self.assertIn(token, plugin_readme)

    def test_parallel_prefix_group_contract_is_documented(self):
        orchestrator = (AGENTS / "orchestrator.md").read_text(encoding="utf-8")
        for token in (
            "next-group",
            "exact filename",
            "worktree_create",
            "worktree_apply",
            "worktree_delete",
            "in parallel",
        ):
            self.assertIn(token, orchestrator)

        _, issues_text = command("issues")
        for token in ("next-group", "every todo", "exact filename", "worktree", "in parallel"):
            self.assertIn(token, issues_text)

        issues_readme = (ROOT / "issues" / "README.md").read_text(encoding="utf-8")
        for token in ("same-prefix", "next-group", "worktree", "exact filename"):
            self.assertIn(token, issues_readme)

        constitution = (ROOT / ".opencode" / "constitution.md").read_text(encoding="utf-8")
        self.assertIn("single-flight per prefix", constitution.lower())
        self.assertIn("worktree", constitution.lower())

    def test_issue_branch_and_acceptance_contract_is_documented(self):
        orchestrator = (AGENTS / "orchestrator.md").read_text(encoding="utf-8")
        for token in (
            "issue_queue.py branch",
            "git rev-parse --verify",
            "worktree_apply",
            "worktree_resolve_conflicts",
            "worktree_delete",
            "deleteBranch",
            "discover -s tests",
            "discover -s sandbox",
            "rev-list --count",
            'deleteBranch: "always"',
            "commitPending: false",
        ):
            self.assertIn(token, orchestrator, token)
        self.assertNotIn("tip differs", orchestrator)
        self.assertNotIn("same tip", orchestrator)

        lead = (AGENTS / "lead.md").read_text(encoding="utf-8")
        self.assertIn("issue_queue.py branch", lead)
        self.assertLowerIn("do not merge into the default branch", lead.lower())
        self.assertIn("leave the branch and worktree intact", lead)
        for token in ("branch", "worktree", "head SHA"):
            self.assertIn(token, lead, token)
        self.assertIn("git rev-parse --verify --quiet refs/heads/<canonical>", lead)
        self.assertIn("worktree_list", lead)
        self.assertIn("Outcome: blocked", lead)

        _, issues_text = command("issues")
        for token in (
            "branch",
            "worktree_apply",
            "worktree_delete",
            "reopen",
            "return",
            "rev-list --count",
            'deleteBranch: "always"',
            "commitPending: false",
        ):
            self.assertIn(token, issues_text, token)

        _, ship_text = command("ship")
        self.assertIn("issue/*", ship_text)
        self.assertIn("acceptance", ship_text)

        issues_readme = (ROOT / "issues" / "README.md").read_text(encoding="utf-8")
        self.assertIn("issue/<id>-<slug>", issues_readme)
        self.assertIn("branch", issues_readme)

        plugin_readme = (
            ROOT / "plugin" / "opencode-worktree" / "README.md"
        ).read_text(encoding="utf-8")
        self.assertIn("issue/<zero-padded id>-<slug>", plugin_readme)
        self.assertIn("acceptance", plugin_readme)

    def test_acceptance_conflict_resolution_contract_is_documented(self):
        def normalized(path: Path) -> str:
            return " ".join(path.read_text(encoding="utf-8").split())

        orchestrator = normalized(AGENTS / "orchestrator.md")
        for token in (
            "acceptance conflict resolver",
            "MERGE_HEAD",
            "--diff-filter=U",
            "HEAD^2",
            "merge-base --is-ancestor",
            "worktree_resolve_conflicts",
            "reviewer",
            "python3 -m unittest discover -s tests",
            "python3 -m unittest discover -s sandbox",
        ):
            self.assertIn(token, orchestrator, token)
        self.assertIn("keep the issue in `review`", orchestrator)
        self.assertIn("never reset", orchestrator)
        for token in (
            "PRE_MERGE",
            "one acceptance at a time",
            "never self-accept",
            "already committed",
        ):
            self.assertIn(token, orchestrator, token)
        self.assertNotIn(
            "If it reports conflicts — or a real merge is in progress", orchestrator
        )
        self.assertNotIn(
            "Never resolve conflicts yourself (you have edit denied) and never reset.",
            orchestrator,
        )

        lead = normalized(AGENTS / "lead.md")
        for token in (
            "acceptance conflict resolver",
            "main checkout",
            "MERGE_HEAD",
            "--diff-filter=U",
            "git add",
            "git commit --no-edit",
            "reviewer",
            "python3 -m unittest discover -s tests",
            "python3 -m unittest discover -s sandbox",
            "Outcome: blocked",
        ):
            self.assertIn(token, lead, token)
        self.assertIn("do not create a worktree", lead)

        _, issues_text = command("issues")
        issues = " ".join(issues_text.split())
        for token in (
            "acceptance conflict resolver",
            "MERGE_HEAD",
            "HEAD^2",
            "is-ancestor",
            "conflicted",
            "worktree_resolve_conflicts",
            "python3 -m unittest discover -s tests",
            "python3 -m unittest discover -s sandbox",
            "PRE_MERGE",
            "one acceptance at a time",
        ):
            self.assertIn(token, issues, token)
        self.assertNotIn("Never resolve conflicts yourself and never reset.", issues)

        for name, text in (("orchestrator", orchestrator), ("issues", issues)):
            with self.subTest(ordering=name):
                self.assertLess(
                    text.index("Probe `MERGE_HEAD` FIRST"),
                    text.index("Only when no `MERGE_HEAD` exists, require clean"),
                )

        constitution = normalized(ROOT / ".opencode" / "constitution.md")
        for token in ("acceptance conflict resolver", "merge commit", "both test suites"):
            self.assertIn(token, constitution, token)
        self.assertIn("never self-accept", constitution.lower())

        for relative in (
            "README.md",
            "PLAN.md",
            "docs/validation.md",
            "plugin/opencode-worktree/README.md",
        ):
            with self.subTest(document=relative):
                text = normalized(ROOT / relative)
                self.assertIn("conflict resolver", text.lower())

        plan = normalized(ROOT / "PLAN.md")
        self.assertIn("issue 004", plan.lower())
        self.assertIn("conflict resolution", plan.lower())
        self.assertNotIn(
            "the orchestrator never resolves conflicts and never resets", plan.lower()
        )

        validation = normalized(ROOT / "docs" / "validation.md")
        self.assertIn("issue 004", validation.lower())
        self.assertIn("conflict resolution", validation.lower())
        self.assertNotIn("orchestrator never resolves conflicts", validation.lower())

    def assertLowerIn(self, needle: str, haystack: str) -> None:
        self.assertIn(needle, haystack)


if __name__ == "__main__":
    unittest.main()
