"""Deterministic git integration tests for squash acceptance (stdlib unittest).

These exercise the mechanics the orchestrator and the acceptance conflict
resolver use: stage an issue branch with ``git merge --squash`` in a temporary
``accept/`` worktree, create exactly one commit, fast-forward the default
branch, and move the local queue state without creating a commit. No model,
network, or plugin runtime is involved.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".opencode" / "scripts" / "issue_queue.py"
GIT = shutil.which("git")
SQUASH_MESSAGE = "issue 005: Keep issue state off main"


@unittest.skipUnless(GIT, "git is required for acceptance integration tests")
class AcceptanceSquashTests(unittest.TestCase):
    default_branch = "main"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.git("init")
        self.git("symbolic-ref", "HEAD", f"refs/heads/{self.default_branch}")
        self.git("config", "user.name", "Test User")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgsign", "false")
        (self.repo / ".opencode" / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPT, self.repo / ".opencode" / "scripts" / "issue_queue.py")

    # Helpers -------------------------------------------------------------

    def git(
        self, *args: str, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [GIT, *args],
            cwd=str(cwd or self.repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check:
            self.assertEqual(
                result.returncode, 0, f"git {' '.join(args)} failed: {result.stderr}"
            )
        return result

    def write(self, relative: str, content: str, cwd: Path | None = None) -> Path:
        path = (cwd or self.repo) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read(self, relative: str, cwd: Path | None = None) -> str:
        return ((cwd or self.repo) / relative).read_text(encoding="utf-8")

    def commit(self, message: str, cwd: Path | None = None) -> None:
        target = cwd or self.repo
        self.git("add", "-A", cwd=target)
        self.git("commit", "-m", message, cwd=target)

    def rev(self, ref: str = "HEAD", cwd: Path | None = None) -> str:
        return self.git("rev-parse", ref, cwd=cwd).stdout.strip()

    def count(self, span: str, cwd: Path | None = None) -> int:
        return int(self.git("rev-list", "--count", span, cwd=cwd).stdout.strip())

    def subjects(self, span: str, cwd: Path | None = None) -> list[str]:
        output = self.git("log", "--format=%s", span, cwd=cwd).stdout
        return [line.strip() for line in output.splitlines() if line.strip()]

    def queue(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.repo / ".opencode" / "scripts" / "issue_queue.py"),
                "--root",
                str(self.repo / "issues"),
                *args,
            ],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def assert_no_merge_head(self, cwd: Path) -> None:
        result = self.git(
            "rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=cwd, check=False
        )
        self.assertNotEqual(result.returncode, 0, "MERGE_HEAD should not exist")

    def delete_accept_worktree(self, path: Path, branch: str) -> None:
        if path.exists():
            self.git("worktree", "remove", "--force", str(path))
        if self.git("branch", "--list", branch).stdout.strip():
            self.git("branch", "-D", branch)
        self.assertFalse(path.exists())
        self.assertEqual(self.git("branch", "--list", branch).stdout.strip(), "")

    def cleanup_worktree(self, path: Path, branch: str) -> None:
        """Best-effort cleanup so a failed assertion leaves no worktree behind."""
        if path.exists():
            self.git("worktree", "remove", "--force", str(path), check=False)
        if self.git("branch", "--list", branch).stdout.strip():
            self.git("branch", "-D", branch, check=False)

    # Clean acceptance ----------------------------------------------------

    def test_clean_squash_acceptance(self) -> None:
        self.write(".gitignore", "/issues/\n")
        self.write("app.txt", "base\n")
        self.commit("base")
        self.write("history.txt", "history\n")
        self.commit("issues: historical management commit")
        base = self.rev()

        self.git("checkout", "-b", "issue/005-demo")
        self.write("app.txt", "one\n")
        self.commit("work one")
        self.write("app.txt", "one\ntwo\n")
        self.commit("work two")
        self.assertEqual(self.count(f"{base}..HEAD"), 2)

        self.git("checkout", self.default_branch)
        pre = self.rev()
        accept = Path(self.tmp.name) / "accept"
        self.git("worktree", "add", "-b", "accept/005-demo", str(accept), pre)
        self.addCleanup(self.cleanup_worktree, accept, "accept/005-demo")

        merge = self.git("merge", "--squash", "issue/005-demo", cwd=accept)
        self.assertEqual(merge.returncode, 0, merge.stderr)
        self.assert_no_merge_head(accept)
        self.assertEqual(
            self.git("diff", "--cached", "--name-only", cwd=accept).stdout.strip(),
            "app.txt",
        )
        self.assertIn(
            "app.txt", self.git("status", "--porcelain", cwd=accept).stdout
        )

        self.git("commit", "-m", SQUASH_MESSAGE, cwd=accept)
        squash = self.rev(cwd=accept)
        self.assertEqual(self.count(f"{pre}..{squash}", cwd=accept), 1)
        self.assertEqual(self.rev(f"{squash}^", cwd=accept), pre)
        self.assertEqual(
            self.subjects(f"{pre}..{squash}", cwd=accept), [SQUASH_MESSAGE]
        )
        self.assertEqual(self.git("status", "--porcelain", cwd=accept).stdout.strip(), "")
        content = self.read("app.txt", cwd=accept)
        self.assertIn("one", content)
        self.assertIn("two", content)

        # Main stays untouched until the explicit fast-forward.
        self.assertEqual(self.rev(), pre)
        self.git("merge", "--ff-only", "accept/005-demo")
        self.assertEqual(self.rev(), squash)
        self.assertEqual(self.count(f"{pre}..HEAD"), 1)
        subjects = self.subjects(f"{pre}..HEAD")
        self.assertEqual(subjects, [SQUASH_MESSAGE])
        self.assertFalse(any(subject.startswith("issues:") for subject in subjects))
        self.assertIn("issues: historical management commit", self.subjects("HEAD"))

        self.write("issues/review/005 Demo.md", "# demo\n")
        commits_before = self.count("HEAD")
        completed = self.queue("complete", "005 Demo.md")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.repo / "issues" / "completed" / "005 Demo.md").is_file())
        self.assertFalse((self.repo / "issues" / "review" / "005 Demo.md").exists())
        self.assertEqual(self.count("HEAD"), commits_before)
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")

        self.delete_accept_worktree(accept, "accept/005-demo")
        self.git("branch", "-D", "issue/005-demo")
        self.assertEqual(
            self.git("branch", "--list", "issue/005-demo").stdout.strip(), ""
        )

    # Conflicting acceptance ---------------------------------------------

    def test_squash_conflict_is_resolved_in_the_accept_worktree(self) -> None:
        self.write(".gitignore", "/issues/\n")
        self.write("app.txt", "base\n")
        self.commit("base")

        self.git("checkout", "-b", "issue/005-conflict")
        self.write("app.txt", "issue\n")
        self.commit("issue side")

        self.git("checkout", self.default_branch)
        self.write("app.txt", "main\n")
        self.commit("main side")
        pre = self.rev()

        accept = Path(self.tmp.name) / "accept-conflict"
        self.git("worktree", "add", "-b", "accept/005-conflict", str(accept), pre)
        self.addCleanup(self.cleanup_worktree, accept, "accept/005-conflict")

        merge = self.git(
            "merge", "--squash", "issue/005-conflict", cwd=accept, check=False
        )
        self.assertNotEqual(merge.returncode, 0)
        conflicted = self.git(
            "diff", "--name-only", "--diff-filter=U", cwd=accept
        ).stdout
        self.assertIn("app.txt", conflicted)
        self.assert_no_merge_head(accept)

        # Main is untouched while the conflict is unresolved.
        self.assertEqual(self.rev(), pre)
        self.assertEqual(self.read("app.txt"), "main\n")

        self.write("app.txt", "main\nissue\n", cwd=accept)
        self.git("add", "app.txt", cwd=accept)
        self.assertEqual(
            self.git("diff", "--name-only", "--diff-filter=U", cwd=accept).stdout.strip(),
            "",
        )
        self.git("commit", "-m", SQUASH_MESSAGE, cwd=accept)
        squash = self.rev(cwd=accept)
        self.assertEqual(self.rev(f"{squash}^", cwd=accept), pre)
        self.assertEqual(
            self.subjects(f"{pre}..{squash}", cwd=accept), [SQUASH_MESSAGE]
        )
        self.assertEqual(self.rev(), pre)
        self.assertEqual(self.count(f"{pre}..HEAD"), 0)

        self.git("merge", "--ff-only", "accept/005-conflict")
        self.assertEqual(self.rev(), squash)
        self.assertEqual(self.count(f"{pre}..HEAD"), 1)
        self.assertEqual(self.subjects(f"{pre}..HEAD"), [SQUASH_MESSAGE])
        content = self.read("app.txt")
        self.assertIn("main", content)
        self.assertIn("issue", content)
        self.assertFalse(
            any(subject.startswith("issues:") for subject in self.subjects(f"{pre}..HEAD"))
        )

        self.delete_accept_worktree(accept, "accept/005-conflict")
        self.git("branch", "-D", "issue/005-conflict")

    # Failure before fast-forward ----------------------------------------

    def test_failed_verification_leaves_main_and_issue_intact(self) -> None:
        self.write(".gitignore", "/issues/\n")
        self.write("app.txt", "base\n")
        self.commit("base")
        base = self.rev()

        self.git("checkout", "-b", "issue/005-demo")
        self.write("app.txt", "one\n")
        self.commit("work one")
        self.write("app.txt", "one\ntwo\n")
        self.commit("work two")
        issue_tip = self.rev()
        self.git("checkout", self.default_branch)

        issue_worktree = Path(self.tmp.name) / "issue-worktree"
        self.git("worktree", "add", str(issue_worktree), "issue/005-demo")
        self.addCleanup(self.cleanup_worktree, issue_worktree, "issue/005-demo")

        pre = self.rev()
        self.assertEqual(pre, base)
        self.write("issues/review/005 Demo.md", "# demo\n")

        accept = Path(self.tmp.name) / "accept-failure"
        self.git("worktree", "add", "-b", "accept/005-failure", str(accept), pre)
        self.addCleanup(self.cleanup_worktree, accept, "accept/005-failure")

        self.git("merge", "--squash", "issue/005-demo", cwd=accept)
        self.git("commit", "-m", SQUASH_MESSAGE, cwd=accept)
        squash = self.rev(cwd=accept)
        self.assertEqual(self.count(f"{pre}..{squash}", cwd=accept), 1)

        # Verification fails: discard only the temporary acceptance worktree.
        self.delete_accept_worktree(accept, "accept/005-failure")

        self.assertEqual(self.rev(), pre)
        self.assertEqual(self.count(f"{pre}..HEAD"), 0)
        self.assertEqual(self.subjects(f"{pre}..HEAD"), [])
        self.assertEqual(self.rev("issue/005-demo"), issue_tip)
        self.assertTrue(issue_worktree.exists())
        self.assertTrue((self.repo / "issues" / "review" / "005 Demo.md").is_file())
        self.assertFalse((self.repo / "issues" / "completed" / "005 Demo.md").exists())
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")

    # Migration/bootstrap ------------------------------------------------

    def test_queue_migration_new_bootstrap_squashes_cleanly(self) -> None:
        self.write(".gitignore", "*.log\n")
        self.write("app.txt", "base\n")
        self.commit("base")
        self.write("issues/inprogress/005 Issue.md", "issue\n")
        self.write("issues/README.md", "# queue\n")
        self.write("issues/.gitignore", ".lock\n")
        self.commit("issues: historical management commit")
        base = self.rev()

        self.git("checkout", "-b", "issue/005-bootstrap")
        self.write(".gitignore", self.read(".gitignore") + "/issues/\n")
        self.git("rm", "-r", "--cached", "issues")
        self.commit("stop tracking the local queue")
        self.git("checkout", self.default_branch)

        # The orchestrator finishes on main with plain filesystem moves, before
        # the migration is accepted: no staging, no commit.
        (self.repo / "issues" / "review").mkdir(parents=True, exist_ok=True)
        os.rename(
            self.repo / "issues" / "inprogress" / "005 Issue.md",
            self.repo / "issues" / "review" / "005 Issue.md",
        )
        # Git quotes paths containing spaces; strip the quoting for comparison.
        status_lines = [
            line.replace('"', "")
            for line in self.git("status", "--porcelain").stdout.splitlines()
        ]
        self.assertEqual(
            sorted(status_lines),
            sorted([" D issues/inprogress/005 Issue.md", "?? issues/review/"]),
        )

        pre = self.rev()
        self.assertEqual(pre, base)
        snapshot = Path(self.tmp.name) / "issues-snapshot"
        shutil.copytree(self.repo / "issues", snapshot)

        accept = Path(self.tmp.name) / "accept-bootstrap"
        self.git("worktree", "add", "-b", "accept/005-bootstrap", str(accept), pre)
        self.addCleanup(self.cleanup_worktree, accept, "accept/005-bootstrap")

        # Main HEAD still tracks issues/inprogress, so the migration merges
        # cleanly even though the local working tree already moved to review.
        merge = self.git("merge", "--squash", "issue/005-bootstrap", cwd=accept)
        self.assertEqual(merge.returncode, 0, merge.stderr)
        self.assert_no_merge_head(accept)
        changed = self.git("diff", "--cached", "--name-only", cwd=accept).stdout
        self.assertIn(".gitignore", changed)
        self.assertIn("issues/inprogress/005 Issue.md", changed)

        self.git("commit", "-m", SQUASH_MESSAGE, cwd=accept)
        squash = self.rev(cwd=accept)
        self.assertEqual(self.count(f"{pre}..{squash}", cwd=accept), 1)
        self.assertEqual(self.rev(f"{squash}^", cwd=accept), pre)
        self.assertEqual(
            self.subjects(f"{pre}..{squash}", cwd=accept), [SQUASH_MESSAGE]
        )
        self.assertEqual(self.rev(), pre)

        self.git("merge", "--ff-only", "accept/005-bootstrap")
        self.assertEqual(self.rev(), squash)
        self.assertEqual(self.count(f"{pre}..HEAD"), 1)
        self.assertEqual(self.git("ls-files", "issues").stdout.strip(), "")
        self.assertTrue((self.repo / "issues" / "review" / "005 Issue.md").is_file())
        self.assertIn("/issues/", self.read(".gitignore"))
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")
        self.assertIn("issues: historical management commit", self.subjects("HEAD"))
        self.assertFalse(
            any(subject.startswith("issues:") for subject in self.subjects(f"{pre}..HEAD"))
        )

        # Restore the local queue captured before acceptance, including the
        # project-owned README/.gitignore, then finish locally without a commit.
        shutil.copytree(snapshot, self.repo / "issues", dirs_exist_ok=True)
        issue_path = self.repo / "issues" / "review" / "005 Issue.md"
        self.assertTrue(issue_path.is_file())
        self.assertTrue((self.repo / "issues" / "README.md").is_file())
        self.assertTrue((self.repo / "issues" / ".gitignore").is_file())
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")
        ignored = self.git(
            "check-ignore", "-q", "--no-index", "issues/review/005 Issue.md", check=False
        )
        self.assertEqual(ignored.returncode, 0, ignored.stderr)

        commits_before = self.count("HEAD")
        completed = self.queue("complete", "005 Issue.md")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.repo / "issues" / "completed" / "005 Issue.md").is_file())
        self.assertFalse(issue_path.exists())
        self.assertEqual(self.count("HEAD"), commits_before)
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")

        self.delete_accept_worktree(accept, "accept/005-bootstrap")
        self.git("branch", "-D", "issue/005-bootstrap")

    def test_queue_migration_committed_finish_falls_back_to_squash(self) -> None:
        self.write(".gitignore", "*.log\n")
        self.write("app.txt", "base\n")
        self.commit("base")
        self.write("issues/inprogress/005 Issue.md", "issue\n")
        self.write("issues/README.md", "# queue\n")
        self.write("issues/.gitignore", ".lock\n")
        self.commit("issues: historical management commit")

        self.git("checkout", "-b", "issue/005-fallback")
        self.write(".gitignore", self.read(".gitignore") + "/issues/\n")
        self.git("rm", "-r", "--cached", "issues")
        self.commit("stop tracking the local queue")
        self.git("checkout", self.default_branch)

        # The older flow committed the local finish before acceptance.
        (self.repo / "issues" / "review").mkdir(parents=True, exist_ok=True)
        self.git("mv", "issues/inprogress/005 Issue.md", "issues/review/005 Issue.md")
        self.commit("issues: finish 005")
        pre = self.rev()

        snapshot = Path(self.tmp.name) / "issues-snapshot-fallback"
        shutil.copytree(self.repo / "issues", snapshot)

        accept = Path(self.tmp.name) / "accept-fallback"
        self.git("worktree", "add", "-b", "accept/005-fallback", str(accept), pre)
        self.addCleanup(self.cleanup_worktree, accept, "accept/005-fallback")

        merge = self.git(
            "merge", "--squash", "issue/005-fallback", cwd=accept, check=False
        )
        self.assertNotEqual(merge.returncode, 0)
        conflicted = self.git(
            "diff", "--name-only", "--diff-filter=U", cwd=accept
        ).stdout
        self.assertIn("005 Issue.md", conflicted)
        self.assert_no_merge_head(accept)

        # The fallback resolve: the queue stays local and untracked.
        self.git("rm", "-r", "--ignore-unmatch", "issues", cwd=accept)
        self.assertEqual(
            self.git("diff", "--name-only", "--diff-filter=U", cwd=accept).stdout.strip(),
            "",
        )
        self.git("commit", "-m", SQUASH_MESSAGE, cwd=accept)
        squash = self.rev(cwd=accept)
        self.assertEqual(self.count(f"{pre}..{squash}", cwd=accept), 1)
        self.assertEqual(self.rev(f"{squash}^", cwd=accept), pre)
        self.assertEqual(
            self.subjects(f"{pre}..{squash}", cwd=accept), [SQUASH_MESSAGE]
        )
        self.assertEqual(
            self.git("ls-tree", "-r", "--name-only", "HEAD", "issues", cwd=accept)
            .stdout.strip(),
            "",
        )
        self.assertIn("/issues/", self.read(".gitignore", cwd=accept))
        self.assertEqual(self.rev(), pre)

        self.git("merge", "--ff-only", "accept/005-fallback")
        self.assertEqual(self.rev(), squash)
        self.assertEqual(self.count(f"{pre}..HEAD"), 1)
        self.assertEqual(self.git("ls-files", "issues").stdout.strip(), "")
        self.assertIn("issues: historical management commit", self.subjects("HEAD"))
        self.assertFalse(
            any(subject.startswith("issues:") for subject in self.subjects(f"{pre}..HEAD"))
        )

        shutil.copytree(snapshot, self.repo / "issues", dirs_exist_ok=True)
        issue_path = self.repo / "issues" / "review" / "005 Issue.md"
        self.assertTrue(issue_path.is_file())
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")
        ignored = self.git(
            "check-ignore", "-q", "--no-index", "issues/review/005 Issue.md", check=False
        )
        self.assertEqual(ignored.returncode, 0, ignored.stderr)

        commits_before = self.count("HEAD")
        completed = self.queue("complete", "005 Issue.md")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.repo / "issues" / "completed" / "005 Issue.md").is_file())
        self.assertFalse(issue_path.exists())
        self.assertEqual(self.count("HEAD"), commits_before)
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")

        self.delete_accept_worktree(accept, "accept/005-fallback")
        self.git("branch", "-D", "issue/005-fallback")


class MasterDefaultBranchAcceptanceTests(AcceptanceSquashTests):
    """Run the same acceptance mechanics when the default branch is master."""

    default_branch = "master"


if __name__ == "__main__":
    unittest.main()
