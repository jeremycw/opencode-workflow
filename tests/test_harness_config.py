"""Structural tests for the opencode harness configuration.

These check the invariants that make issue orchestration and depth-2 dispatch
work: the orchestrator is the default primary, the lead can be a subagent, the
specialists cannot delegate, and the installer/docs/scaffolding travel with the
harness. They intentionally avoid live model sessions.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from _frontmatter import load_frontmatter

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / ".opencode" / "agents"
COMMANDS = ROOT / ".opencode" / "commands"
TEMPLATE_ISSUES = ROOT / "plugin" / "opencode-worktree" / "templates" / "issues"
GIT = shutil.which("git")


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
        self.assertIn('ISSUES_SRC="$SCRIPT_DIR/templates/issues"', installer)
        self.assertNotIn('ISSUES_SRC="$HARNESS_ROOT/issues"', installer)
        self.assertNotIn('grep -qxF -- "issues/" "$file"', installer)
        self.assertIn('grep -qxF -- "$line" "$file"', installer)
        for token in (
            "scripts/issue_queue.py",
            "templates/issues",
            "/issues/",
            "ensure_root_gitignore",
            "git rm -r --cached issues",
            "issues/README.md",
            "issues/.gitignore",
            ".gitkeep",
        ):
            self.assertIn(token, installer)

    def test_issue_scaffolding_exists(self):
        issues = TEMPLATE_ISSUES
        for state in ("todo", "inprogress", "review", "completed"):
            with self.subTest(state=state):
                self.assertTrue((issues / state).is_dir())
                self.assertTrue((issues / state / ".gitkeep").is_file())
        self.assertTrue((issues / "README.md").is_file())
        self.assertIn(".lock", (issues / ".gitignore").read_text(encoding="utf-8"))

    @unittest.skipUnless(GIT, "git is required to inspect the index")
    def test_local_queue_is_untracked_and_ignored(self):
        def git(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", *args],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )

        tracked = git("ls-files", "issues")
        self.assertEqual(tracked.returncode, 0, tracked.stderr)
        self.assertEqual(tracked.stdout.strip(), "")

        ignored = git("check-ignore", "-q", "--no-index", "issues/README.md")
        self.assertEqual(ignored.returncode, 0, ignored.stderr)

        template = git(
            "check-ignore",
            "-q",
            "--no-index",
            "plugin/opencode-worktree/templates/issues/README.md",
        )
        self.assertEqual(template.returncode, 1, template.stderr)

        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/issues/", lines)

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
            "worktree_delete",
            "in parallel",
        ):
            self.assertIn(token, orchestrator)

        _, issues_text = command("issues")
        for token in ("next-group", "every todo", "exact filename", "worktree", "in parallel"):
            self.assertIn(token, issues_text)

        issues_readme = (TEMPLATE_ISSUES / "README.md").read_text(encoding="utf-8")
        for token in ("same-prefix", "next-group", "worktree", "exact filename"):
            self.assertIn(token, issues_readme)

        constitution = (ROOT / ".opencode" / "constitution.md").read_text(encoding="utf-8")
        self.assertIn("single-flight per prefix", constitution.lower())
        self.assertIn("worktree", constitution.lower())

    def test_issue_branch_and_squash_acceptance_contract_is_documented(self):
        def normalized(path: Path) -> str:
            return " ".join(path.read_text(encoding="utf-8").split())

        orchestrator = normalized(AGENTS / "orchestrator.md")
        self.assert_tokens(
            orchestrator,
            (
                "issue_queue.py branch",
                "git rev-parse --verify",
                "worktree_create",
                "merge --squash",
                "accept/",
                "--ff-only",
                "rev-list --count",
                'deleteBranch: "always"',
                "commitPending: false",
                "PRE_MERGE",
                "snapshot",
                "restore",
                "acceptance conflict resolver",
                "--diff-filter=U",
                "reviewer",
                "python3 -m unittest discover -s tests",
                "python3 -m unittest discover -s sandbox",
                "keep the issue in `review`",
                "never reset",
                "one acceptance at a time",
                "never self-accept",
            ),
        )
        for old in (
            "git add issues",
            'git commit -m "issues:',
            'worktree_apply(branch, mode: "merge")',
        ):
            self.assertNotIn(old, orchestrator, old)

        lead = normalized(AGENTS / "lead.md")
        self.assert_tokens(
            lead,
            (
                "issue_queue.py branch",
                "git rev-parse --verify --quiet refs/heads/<canonical>",
                "worktree_list",
                "Outcome: blocked",
                "leave the branch and worktree intact",
                "do not merge into the default branch",
                "acceptance conflict resolver",
                "accept/",
                "temporary",
                "merge --squash",
                "--diff-filter=U",
                "git add",
                'git commit -m "issue',
                "reviewer",
                "python3 -m unittest discover -s tests",
                "python3 -m unittest discover -s sandbox",
                "do not create a worktree",
                "never touch the main checkout",
            ),
        )
        self.assertNotIn("git commit --no-edit", lead)

        _, issues_text = command("issues")
        issues = " ".join(issues_text.split())
        self.assert_tokens(
            issues,
            (
                "next-group",
                "every todo",
                "exact filename",
                "worktree",
                "in parallel",
                "branch",
                "worktree_create",
                "worktree_delete",
                "merge --squash",
                "accept/",
                "--ff-only",
                "rev-list --count",
                'deleteBranch: "always"',
                "commitPending: false",
                "PRE_MERGE",
                "snapshot",
                "restore",
                "acceptance conflict resolver",
                "--diff-filter=U",
                "python3 -m unittest discover -s tests",
                "python3 -m unittest discover -s sandbox",
                "reopen",
                "return",
            ),
        )
        for old in (
            "git add issues",
            "MERGE_HEAD",
            "HEAD^2",
            "worktree_resolve_conflicts",
            "git commit --no-edit",
        ):
            self.assertNotIn(old, issues, old)

        _, ship_text = command("ship")
        self.assertIn("issue/*", ship_text)
        self.assertIn("acceptance", ship_text)

        issues_readme = (TEMPLATE_ISSUES / "README.md").read_text(encoding="utf-8")
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
        self.assert_tokens(
            orchestrator,
            (
                "acceptance conflict resolver",
                "--diff-filter=U",
                "reviewer",
                "python3 -m unittest discover -s tests",
                "python3 -m unittest discover -s sandbox",
                "keep the issue in `review`",
                "never reset",
                "PRE_MERGE",
                "one acceptance at a time",
                "never self-accept",
            ),
        )
        for old in (
            "MERGE_HEAD",
            "HEAD^2",
            "worktree_resolve_conflicts",
            "git commit --no-edit",
        ):
            self.assertNotIn(old, orchestrator, old)

        lead = normalized(AGENTS / "lead.md")
        self.assert_tokens(
            lead,
            (
                "acceptance conflict resolver",
                "accept/",
                "temporary",
                "merge --squash",
                "--diff-filter=U",
                "git add",
                'git commit -m "issue',
                "reviewer",
                "python3 -m unittest discover -s tests",
                "python3 -m unittest discover -s sandbox",
                "Outcome: blocked",
                "do not create a worktree",
                "never touch the main checkout",
            ),
        )
        self.assertNotIn("git commit --no-edit", lead)

        constitution = normalized(ROOT / ".opencode" / "constitution.md")
        lower = constitution.lower()
        for token in (
            "squash",
            "accept/",
            "local",
            "both test suites",
            "never self-accept",
        ):
            self.assertIn(token, lower, token)
        self.assertTrue("untracked" in lower or "git-ignored" in lower)
        for old in (
            "MERGE_HEAD",
            "HEAD^2",
            "git commit --no-edit",
            'mode: "merge"',
            "merge-base --is-ancestor",
        ):
            self.assertNotIn(old, constitution, old)

        for relative in (
            "README.md",
            "PLAN.md",
            "docs/validation.md",
            "plugin/opencode-worktree/README.md",
        ):
            with self.subTest(document=relative):
                self.assertIn("squash", normalized(ROOT / relative).lower())

        plan = normalized(ROOT / "PLAN.md").lower()
        self.assertIn("issue 005", plan)
        self.assertIn("issue 004", plan)
        self.assertIn("conflict resolution", plan)

        validation = normalized(ROOT / "docs" / "validation.md").lower()
        self.assertIn("issue 005", validation)
        self.assertIn("issue 004", validation)
        self.assertIn("conflict resolution", validation)
        self.assertIn("bootstrap", validation)

        template_readme = normalized(TEMPLATE_ISSUES / "README.md")
        template_lower = template_readme.lower()
        self.assertTrue("git-ignored" in template_lower or "untracked" in template_lower)
        for token in ("accept/", "snapshot"):
            self.assertIn(token, template_readme, token)

    def test_no_queue_state_commits_are_instructed(self):
        documents = {
            ".opencode/agents/orchestrator.md": (AGENTS / "orchestrator.md").read_text(
                encoding="utf-8"
            ),
            ".opencode/agents/lead.md": (AGENTS / "lead.md").read_text(encoding="utf-8"),
            ".opencode/commands/issues.md": command("issues")[1],
            ".opencode/constitution.md": (
                ROOT / ".opencode" / "constitution.md"
            ).read_text(encoding="utf-8"),
            "plugin/opencode-worktree/templates/issues/README.md": (
                TEMPLATE_ISSUES / "README.md"
            ).read_text(encoding="utf-8"),
            "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
            "AGENTS.md": (ROOT / "AGENTS.md").read_text(encoding="utf-8"),
            "plugin/opencode-worktree/README.md": (
                ROOT / "plugin" / "opencode-worktree" / "README.md"
            ).read_text(encoding="utf-8"),
        }
        for name, text in documents.items():
            with self.subTest(document=name):
                for forbidden in (
                    "git add issues",
                    "git commit -- issues",
                    'git commit -m "issues:',
                ):
                    self.assertNotIn(forbidden, text, f"{name}: {forbidden}")

    def assert_tokens(self, text: str, tokens: tuple[str, ...]) -> None:
        lower = text.lower()
        for token in tokens:
            haystack = text if any(character.isupper() for character in token) else lower
            self.assertIn(token, haystack, token)

    def assertLowerIn(self, needle: str, haystack: str) -> None:
        self.assertIn(needle, haystack)


if __name__ == "__main__":
    unittest.main()
