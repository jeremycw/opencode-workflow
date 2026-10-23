"""Behavioral tests for scripts/issue_queue.py (stdlib unittest, temp dirs)."""

from __future__ import annotations

import errno
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "issue_queue.py"

sys.path.insert(0, str(ROOT / "scripts"))
import issue_queue as queue  # noqa: E402  (path set up immediately above)

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


class QueueTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "issues"
        for state in queue.STATES:
            (self.root / state).mkdir(parents=True)

    def write(self, state: str, name: str, body: str | None = None) -> Path:
        path = self.root / state / name
        path.write_text(body if body is not None else f"# {name}\n", encoding="utf-8")
        return path

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )


class ParsingTests(QueueTestCase):
    def test_parses_titles_with_spaces_and_ignores_non_issues(self):
        self.write("todo", "001 First issue with spaces.md")
        self.write("todo", "README.md")
        self.write("todo", ".gitkeep")
        self.write("todo", ".hidden.md")
        self.write("todo", "notes.txt")

        issues = queue.scan(self.root)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].id, "001")
        self.assertEqual(issues[0].title, "First issue with spaces")
        self.assertEqual(issues[0].state, "todo")

    def test_numeric_order_not_lexicographic(self):
        self.write("todo", "010 Ten.md")
        self.write("todo", "002 Two.md")
        self.write("todo", "001 One.md")

        self.assertEqual([issue.id for issue in queue.scan(self.root)], ["001", "002", "010"])
        self.assertEqual(queue.next_issue(self.root).id, "001")

    def test_duplicate_prefix_across_states_is_an_error(self):
        self.write("todo", "001 Same.md")
        self.write("review", "001 Different title.md")

        with self.assertRaises(queue.QueueError) as caught:
            queue.scan(self.root)
        self.assertIn("duplicate issue prefix 001", str(caught.exception))

    def test_nonconforming_markdown_is_reported_not_fatal(self):
        self.write("todo", "001 Good.md")
        self.write("todo", "not-an-issue.md")
        self.assertEqual(queue.nonconforming(self.root), [("todo", "not-an-issue.md")])
        self.assertEqual(len(queue.scan(self.root)), 1)

    def test_symlinks_are_ignored(self):
        self.write("todo", "001 Good.md")
        (self.root / "todo" / "002 Link.md").symlink_to(self.root / "todo" / "001 Good.md")
        (self.root / "todo" / "not-an-issue-link.md").symlink_to(
            self.root / "todo" / "001 Good.md"
        )
        self.assertEqual([issue.id for issue in queue.scan(self.root)], ["001"])
        self.assertEqual(queue.nonconforming(self.root), [])


class LookupTests(QueueTestCase):
    def test_find_by_numeric_id_and_exact_filename(self):
        self.write("todo", "001 Some title.md")
        self.assertEqual(queue.find("001", self.root).filename, "001 Some title.md")
        self.assertEqual(queue.find("1", self.root).id, "001")
        self.assertEqual(queue.find("001 Some title.md", self.root).id, "001")

    def test_missing_id_is_an_error(self):
        self.write("todo", "001 Some title.md")
        with self.assertRaises(queue.QueueError):
            queue.find("999", self.root)
        with self.assertRaises(queue.QueueError):
            queue.find("nope.md", self.root)

    def test_duplicate_prefix_makes_lookup_ambiguous(self):
        self.write("todo", "001 First.md")
        self.write("review", "001 Second.md")
        with self.assertRaises(queue.QueueError):
            queue.find("001", self.root)


class TransitionTests(QueueTestCase):
    def test_start_moves_and_single_flight_refuses_second_claim(self):
        self.write("todo", "001 First.md")
        self.write("todo", "002 Second.md")

        moved = queue.start("001", self.root)
        self.assertTrue(moved.is_file())
        self.assertEqual(moved.parent.name, "inprogress")
        self.assertFalse((self.root / "todo" / "001 First.md").exists())

        with self.assertRaises(queue.QueueError) as caught:
            queue.start("002", self.root)
        self.assertIn("already in progress", str(caught.exception))
        self.assertTrue((self.root / "todo" / "002 Second.md").is_file())

        queue.finish("001", self.root)
        queue.start("002", self.root)

    def test_wrong_state_transitions_are_refused(self):
        self.write("todo", "001 Issue.md")

        for function in (queue.finish, queue.complete, queue.reopen, queue.return_to_todo):
            with self.subTest(function=function.__name__):
                with self.assertRaises(queue.QueueError):
                    function("001", self.root)

        queue.start("001", self.root)
        with self.assertRaises(queue.QueueError):
            queue.start("001", self.root)
        for function in (queue.complete, queue.reopen):
            with self.subTest(function=function.__name__):
                with self.assertRaises(queue.QueueError):
                    function("001", self.root)

        sent_back = queue.return_to_todo("001", self.root)
        self.assertEqual(sent_back.parent.name, "todo")

        queue.start("001", self.root)
        queue.finish("001", self.root)
        with self.assertRaises(queue.QueueError):
            queue.finish("001", self.root)
        with self.assertRaises(queue.QueueError):
            queue.return_to_todo("001", self.root)

        reopened = queue.reopen("001", self.root)
        self.assertEqual(reopened.parent.name, "todo")

        queue.start("001", self.root)
        queue.finish("001", self.root)
        completed = queue.complete("001", self.root)
        self.assertEqual(completed.parent.name, "completed")
        with self.assertRaises(queue.QueueError):
            queue.complete("001", self.root)

    def test_start_requires_lowest_todo_issue(self):
        self.write("todo", "001 First.md")
        self.write("todo", "010 Tenth.md")

        with self.assertRaises(queue.QueueError) as caught:
            queue.start("010", self.root)
        self.assertIn("start 001 first", str(caught.exception))
        self.assertTrue((self.root / "todo" / "010 Tenth.md").is_file())

        queue.start("001", self.root)
        queue.finish("001", self.root)
        queue.start("010", self.root)
        self.assertTrue((self.root / "inprogress" / "010 Tenth.md").is_file())

    def test_moves_never_clobber(self):
        source = self.write("todo", "001 Issue.md", "source\n")
        destination = self.write("inprogress", "001 Issue.md", "destination\n")

        # scan() rejects duplicate prefixes first, so exercise the move helper
        # directly to prove the no-clobber guarantee itself.
        with self.assertRaises(queue.QueueError) as caught:
            queue._move_no_clobber(source, destination, self.root)
        self.assertIn("refusing to overwrite", str(caught.exception))
        self.assertEqual(source.read_text(encoding="utf-8"), "source\n")
        self.assertEqual(destination.read_text(encoding="utf-8"), "destination\n")

        # The high-level command also refuses the ambiguous queue.
        with self.assertRaises(queue.QueueError):
            queue.start("001", self.root)


class MoveTests(QueueTestCase):
    def test_normal_move_is_atomic_rename(self):
        source = self.write("todo", "001 Issue.md", "source\n")
        destination = self.root / "inprogress" / "001 Issue.md"

        queue._move_no_clobber(source, destination, self.root)

        self.assertFalse(source.exists())
        self.assertEqual(destination.read_text(encoding="utf-8"), "source\n")

    def test_cross_device_fallback_copies_and_cleans_up(self):
        source = self.write("todo", "001 Issue.md", "source\n")
        destination = self.root / "inprogress" / "001 Issue.md"

        with mock.patch.object(
            queue.os, "rename", side_effect=OSError(errno.EXDEV, "cross-device link")
        ):
            queue._move_no_clobber(source, destination, self.root)

        self.assertFalse(source.exists())
        self.assertEqual(destination.read_text(encoding="utf-8"), "source\n")
        self.assertEqual(list(destination.parent.glob(".issue-*")), [])

    def test_cross_device_fallback_refuses_late_destination(self):
        source = self.write("todo", "001 Issue.md", "source\n")
        destination = self.root / "inprogress" / "001 Issue.md"

        def late_link(src: str, dst: str) -> None:
            Path(dst).write_text("late\n", encoding="utf-8")
            raise FileExistsError(errno.EEXIST, "file exists")

        with mock.patch.object(
            queue.os, "rename", side_effect=OSError(errno.EXDEV, "cross-device link")
        ), mock.patch.object(queue.os, "link", side_effect=late_link):
            with self.assertRaises(queue.QueueError) as caught:
                queue._move_no_clobber(source, destination, self.root)

        self.assertIn("refusing to overwrite", str(caught.exception))
        self.assertTrue(source.is_file())
        self.assertEqual(destination.read_text(encoding="utf-8"), "late\n")
        self.assertEqual(list(destination.parent.glob(".issue-*")), [])


class StatusAndCliTests(QueueTestCase):
    def test_status_counts_and_lists_each_state(self):
        self.write("todo", "001 Todo.md")
        self.write("review", "002 Review.md")
        self.write("completed", "003 Done.md")

        lines = queue.status_lines(self.root)
        self.assertIn("todo: 1", lines)
        self.assertIn("review: 1", lines)
        self.assertIn("completed: 1", lines)
        self.assertIn("inprogress: 0", lines)
        self.assertTrue(any("issues/todo/001 Todo.md" in line for line in lines))

    def test_cli_status_warns_on_nonconforming_markdown(self):
        self.write("todo", "001 Good.md")
        self.write("todo", "notes.md")
        status = self.run_cli("status")
        self.assertEqual(status.returncode, 0)
        self.assertIn("warning:", status.stderr)
        self.assertIn("notes.md", status.stderr)

    def test_cli_exit_codes_and_output(self):
        self.write("todo", "001 First.md")
        self.write("todo", "002 Second.md")

        started = self.run_cli("start", "001")
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertIn("issues/inprogress/001 First.md", started.stdout)

        blocked = self.run_cli("start", "002")
        self.assertEqual(blocked.returncode, 1)
        self.assertTrue(blocked.stderr.startswith("error:"))

        wrong_state = self.run_cli("complete", "001")
        self.assertEqual(wrong_state.returncode, 1)

        missing_argument = self.run_cli("start")
        self.assertEqual(missing_argument.returncode, 2)

        bad_state = self.run_cli("list", "nonsense")
        self.assertEqual(bad_state.returncode, 2)

        status = self.run_cli("status")
        self.assertEqual(status.returncode, 0)
        self.assertIn("inprogress: 1", status.stdout)

        next_command = self.run_cli("next")
        self.assertEqual(next_command.returncode, 0)
        self.assertIn("issues/todo/002 Second.md", next_command.stdout)

        listed = self.run_cli("list", "todo")
        self.assertEqual(listed.returncode, 0)
        self.assertEqual(listed.stdout.strip().splitlines(), ["issues/todo/002 Second.md"])

    @unittest.skipIf(fcntl is None, "fcntl unavailable on this platform")
    def test_mutations_block_on_the_queue_lock(self):
        self.write("todo", "001 First.md")
        lock_path = self.root / ".lock"
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import fcntl,sys,time; f=open(sys.argv[1],'a+'); "
                "fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); time.sleep(1.0)",
                str(lock_path),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: holder.poll() is None and holder.kill())
        try:
            assert holder.stdout is not None
            self.assertEqual(holder.stdout.readline().strip(), "locked")

            start = subprocess.Popen(
                [sys.executable, str(SCRIPT), "--root", str(self.root), "start", "001"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    start.wait(timeout=0.25)
            finally:
                holder.wait(timeout=5)
                holder.stdout.close()
                stdout, stderr = start.communicate(timeout=10)

            self.assertEqual(start.returncode, 0, stderr)
            self.assertIn("inprogress", stdout)
            self.assertTrue(lock_path.exists())
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait(timeout=5)

    @unittest.skipIf(fcntl is None, "fcntl unavailable on this platform")
    def test_reads_block_on_the_queue_lock(self):
        self.write("todo", "001 First.md")
        lock_path = self.root / ".lock"
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import fcntl,sys,time; f=open(sys.argv[1],'a+'); "
                "fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); time.sleep(1.0)",
                str(lock_path),
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: holder.poll() is None and holder.kill())
        try:
            assert holder.stdout is not None
            self.assertEqual(holder.stdout.readline().strip(), "locked")

            status = subprocess.Popen(
                [sys.executable, str(SCRIPT), "--root", str(self.root), "status"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    status.wait(timeout=0.25)
            finally:
                holder.wait(timeout=5)
                holder.stdout.close()
                stdout, stderr = status.communicate(timeout=10)

            self.assertEqual(status.returncode, 0, stderr)
            self.assertIn("todo: 1", stdout)
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
