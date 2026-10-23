#!/usr/bin/env python3
"""Deterministic issue queue for the opencode engineering harness.

Issues live in one of four state directories under ``issues/``::

    issues/todo/<NNN> <title>.md
    issues/inprogress/<NNN> <title>.md
    issues/review/<NNN> <title>.md
    issues/completed/<NNN> <title>.md

The numeric prefix is the issue id. Files are ordered by the integer value of
that prefix, never lexicographically. Mutations are no-clobber moves and (when
``fcntl`` is available) hold an exclusive lock on ``issues/.lock`` so two
agents cannot claim work at the same time. Reads hold a shared lock so they
never observe an issue in two states mid-move.

Exit codes: 0 success, 1 domain error, 2 argparse usage error.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import errno
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterator, Optional, Sequence

try:  # pragma: no cover - exercised only on platforms without fcntl
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

STATES = ("todo", "inprogress", "review", "completed")
IGNORED_NAMES = {"readme.md", ".gitkeep", ".gitignore"}
ISSUE_RE = re.compile(r"^(\d{3,})\s+(.+)\.md$")
DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "issues"


class QueueError(Exception):
    """A domain error (exit code 1), not a usage error."""


@dataclasses.dataclass(frozen=True)
class Issue:
    """One issue file in one queue state."""

    number: int
    title: str
    filename: str
    state: str
    path: Path

    @property
    def id(self) -> str:
        """Canonical id: the numeric prefix padded to at least three digits."""
        return f"{self.number:03d}"

    @property
    def sort_key(self) -> tuple[int, str]:
        """Numeric ordering, then filename as a stable tie-breaker."""
        return (self.number, self.filename)


def _root(root: Optional[os.PathLike[str] | str]) -> Path:
    return Path(root) if root is not None else DEFAULT_ROOT


def _is_ignored(name: str) -> bool:
    return name.startswith(".") or name.lower() in IGNORED_NAMES


def _state_dir(root: Path, state: str) -> Path:
    return root / state


def _relpath(path: Path, root: Path) -> str:
    """Render a queue path relative to the repository root (parent of issues/)."""
    return os.path.relpath(path, root.parent)


def ensure_layout(root: Optional[os.PathLike[str] | str] = None) -> Path:
    """Create the queue root and its state directories if needed."""
    base = _root(root)
    for state in STATES:
        _state_dir(base, state).mkdir(parents=True, exist_ok=True)
    return base


@contextlib.contextmanager
def _locked(root: Path, shared: bool = False) -> Iterator[None]:
    """Lock ``issues/.lock``: shared for reads, exclusive for mutations.

    A shared read never creates the queue root or the lock file: when the root
    does not exist there is nothing to read, so yield without locking.
    """
    if shared and not root.is_dir():
        yield
        return

    root.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover - no-op fallback
        yield
        return

    lock_path = root / ".lock"
    mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), mode)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _nonconforming_unlocked(base: Path) -> list[tuple[str, str]]:
    bad: list[tuple[str, str]] = []
    for state in STATES:
        directory = _state_dir(base, state)
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            if entry.is_symlink():
                continue
            if entry.name.startswith(".") or entry.name.lower() in IGNORED_NAMES:
                continue
            if entry.is_file() and entry.suffix.lower() == ".md" and not ISSUE_RE.match(entry.name):
                bad.append((state, entry.name))
    return bad


def nonconforming(root: Optional[os.PathLike[str] | str] = None) -> list[tuple[str, str]]:
    """Return ``(state, filename)`` pairs for .md files that do not match the scheme."""
    base = _root(root)
    with _locked(base, shared=True):
        return _nonconforming_unlocked(base)


def _scan_unlocked(base: Path) -> list[Issue]:
    issues: list[Issue] = []
    seen: dict[int, Issue] = {}

    for state in STATES:
        directory = _state_dir(base, state)
        if not directory.is_dir():
            continue
        for entry in sorted(directory.iterdir()):
            if entry.is_symlink() or not entry.is_file():
                continue
            if _is_ignored(entry.name):
                continue
            match = ISSUE_RE.match(entry.name)
            if not match:
                continue
            number = int(match.group(1))
            issue = Issue(
                number=number,
                title=match.group(2),
                filename=entry.name,
                state=state,
                path=entry,
            )
            previous = seen.get(number)
            if previous is not None:
                raise QueueError(
                    "duplicate issue prefix "
                    f"{number:03d}: {_relpath(previous.path, base)} and "
                    f"{_relpath(issue.path, base)}"
                )
            seen[number] = issue
            issues.append(issue)

    return sorted(issues, key=lambda issue: issue.sort_key)


def scan(root: Optional[os.PathLike[str] | str] = None) -> list[Issue]:
    """Scan every state and return issues in numeric order.

    Raises :class:`QueueError` if two files share a numeric prefix (across any
    state), because ids would be ambiguous.
    """
    base = _root(root)
    with _locked(base, shared=True):
        return _scan_unlocked(base)


def _issues_in_unlocked(state: str, base: Path) -> list[Issue]:
    if state not in STATES:
        raise QueueError(f"unknown state: {state} (expected one of {', '.join(STATES)})")
    return [issue for issue in _scan_unlocked(base) if issue.state == state]


def issues_in(state: str, root: Optional[os.PathLike[str] | str] = None) -> list[Issue]:
    """Return issues in one state, validated and numerically ordered."""
    base = _root(root)
    with _locked(base, shared=True):
        return _issues_in_unlocked(state, base)


def _find_unlocked(identifier: str, base: Path) -> Issue:
    issues = _scan_unlocked(base)
    identifier = identifier.strip()
    if not identifier:
        raise QueueError("issue id is empty")

    if identifier.isdigit():
        number = int(identifier)
        matches = [issue for issue in issues if issue.number == number]
    else:
        matches = [issue for issue in issues if issue.filename == identifier]

    if not matches:
        raise QueueError(f"issue not found: {identifier}")
    if len(matches) > 1:
        names = ", ".join(issue.filename for issue in matches)
        raise QueueError(f"ambiguous issue id {identifier!r}: {names}")
    return matches[0]


def find(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> Issue:
    """Find an issue by numeric id or exact filename."""
    base = _root(root)
    with _locked(base, shared=True):
        return _find_unlocked(identifier, base)


def next_issue(root: Optional[os.PathLike[str] | str] = None) -> Optional[Issue]:
    """Return the lowest-numbered todo issue, or ``None`` when the queue is empty."""
    base = _root(root)
    with _locked(base, shared=True):
        todo = _issues_in_unlocked("todo", base)
        return todo[0] if todo else None


def status_lines(root: Optional[os.PathLike[str] | str] = None) -> list[str]:
    """Build the human-readable queue status (one block per state)."""
    base = _root(root)
    with _locked(base, shared=True):
        issues = _scan_unlocked(base)
    lines: list[str] = []
    for state in STATES:
        members = [issue for issue in issues if issue.state == state]
        lines.append(f"{state}: {len(members)}")
        for issue in members:
            lines.append(f"  {_relpath(issue.path, base)}")
    return lines


def _move_no_clobber(source: Path, destination: Path, root: Path) -> Path:
    """Move ``source`` to ``destination`` without ever overwriting a file.

    ``os.rename`` is atomic on one filesystem. Cross-device moves fall back to
    a hidden temp file in the destination directory, published without clobber.
    """
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise QueueError(
            f"could not create {_relpath(destination.parent, root)}: "
            f"{error.strerror or error}"
        ) from None
    if destination.exists() or destination.is_symlink():
        raise QueueError(
            f"refusing to overwrite {_relpath(destination, root)}: destination already exists"
        )

    try:
        os.rename(source, destination)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise QueueError(
                f"could not move {_relpath(source, root)}: {error.strerror or error}"
            ) from None
    else:
        return destination

    # Cross-device: copy beside the destination, then publish without clobber.
    temp_path: Optional[Path] = None
    try:
        descriptor, temp_name = tempfile.mkstemp(prefix=".issue-", dir=destination.parent)
        temp_path = Path(temp_name)
        with os.fdopen(descriptor, "wb") as out, open(source, "rb") as incoming:
            shutil.copyfileobj(incoming, out)
        try:
            shutil.copystat(source, temp_path)
        except OSError:
            # Metadata preservation is best-effort; the move itself succeeded.
            pass

        try:
            os.link(temp_path, destination)
        except FileExistsError:
            raise QueueError(
                f"refusing to overwrite {_relpath(destination, root)}: destination already exists"
            ) from None
        except OSError:
            # Filesystem without hardlinks: re-check, then atomically publish.
            if destination.exists() or destination.is_symlink():
                raise QueueError(
                    f"refusing to overwrite {_relpath(destination, root)}: destination already exists"
                ) from None
            os.replace(temp_path, destination)

        try:
            source.unlink()
        except OSError as error:
            # Do not leave both paths behind; best-effort roll back the publish.
            try:
                destination.unlink()
            except OSError:
                pass
            raise QueueError(
                f"could not remove {_relpath(source, root)} after copy: "
                f"{error.strerror or error}"
            ) from None
    except OSError as error:
        raise QueueError(
            f"could not move {_relpath(source, root)}: {error.strerror or error}"
        ) from None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
    return destination


def _transition(
    identifier: str,
    expected: str,
    target: str,
    root: Optional[os.PathLike[str] | str] = None,
) -> Path:
    base = ensure_layout(root)
    with _locked(base):
        issue = _find_unlocked(identifier, base)
        if issue.state != expected:
            raise QueueError(
                f"issue {issue.id} is in {issue.state}, expected {expected} "
                f"for this transition"
            )
        destination = _state_dir(base, target) / issue.filename
        return _move_no_clobber(issue.path, destination, base)


def _start(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> Path:
    base = ensure_layout(root)
    with _locked(base):
        issue = _find_unlocked(identifier, base)
        if issue.state != "todo":
            raise QueueError(
                f"issue {issue.id} is in {issue.state}, expected todo for start"
            )
        todo = _issues_in_unlocked("todo", base)
        if todo and todo[0].number != issue.number:
            raise QueueError(
                f"issue {issue.id} is not next in numeric order: "
                f"start {todo[0].id} first"
            )
        active = _issues_in_unlocked("inprogress", base)
        if active:
            current = active[0]
            raise QueueError(
                "another issue is already in progress: "
                f"{current.filename} (only one issue may be in progress at a time)"
            )
        destination = _state_dir(base, "inprogress") / issue.filename
        return _move_no_clobber(issue.path, destination, base)


# Public mutation API -------------------------------------------------------


def start(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> Path:
    """Claim a todo issue: todo -> inprogress (single-flight enforced)."""
    return _start(identifier, root)


def finish(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> Path:
    """Move a completed implementation to user review: inprogress -> review."""
    return _transition(identifier, "inprogress", "review", root)


def complete(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> Path:
    """Accept a reviewed issue: review -> completed."""
    return _transition(identifier, "review", "completed", root)


def reopen(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> Path:
    """Reject a reviewed issue: review -> todo."""
    return _transition(identifier, "review", "todo", root)


def return_to_todo(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> Path:
    """Return a failed/interrupted issue: inprogress -> todo."""
    return _transition(identifier, "inprogress", "todo", root)


# CLI ----------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the issues/ queue: numeric order, single-flight, no-clobber moves."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="queue root (default: <repo>/issues)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="show counts and issues per state")
    list_parser = subparsers.add_parser("list", help="list issues in one state")
    list_parser.add_argument("state", choices=STATES)
    subparsers.add_parser("next", help="show the next todo issue")

    for name, help_text in (
        ("start", "claim a todo issue (todo -> inprogress)"),
        ("finish", "send an inprogress issue to review (inprogress -> review)"),
        ("complete", "accept a reviewed issue (review -> completed)"),
        ("reopen", "reject a reviewed issue (review -> todo)"),
        ("return", "return an inprogress issue to todo (inprogress -> todo)"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("id", help="numeric prefix (e.g. 001) or exact filename")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root

    try:
        if args.command == "status":
            for line in status_lines(root):
                print(line)
            for state, filename in nonconforming(root):
                print(
                    f"warning: ignoring non-conforming issue filename in {state}: {filename}",
                    file=sys.stderr,
                )
            return 0

        if args.command == "list":
            base = _root(root)
            for issue in issues_in(args.state, base):
                print(_relpath(issue.path, base))
            return 0

        if args.command == "next":
            issue = next_issue(root)
            if issue is None:
                print("none")
            else:
                print(_relpath(issue.path, _root(root)))
            return 0

        if args.command == "start":
            path = start(args.id, root)
        elif args.command == "finish":
            path = finish(args.id, root)
        elif args.command == "complete":
            path = complete(args.id, root)
        elif args.command == "reopen":
            path = reopen(args.id, root)
        elif args.command == "return":
            path = return_to_todo(args.id, root)
        else:  # pragma: no cover - argparse enforces the choices
            raise QueueError(f"unknown command: {args.command}")

        print(_relpath(path, _root(root)))
        return 0
    except QueueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
