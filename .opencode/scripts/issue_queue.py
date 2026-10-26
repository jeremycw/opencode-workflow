#!/usr/bin/env python3
"""Deterministic issue queue for the opencode engineering harness.

Issues live in one of four state directories under ``issues/``::

    issues/todo/<NNN> <title>.md
    issues/inprogress/<NNN> <title>.md
    issues/review/<NNN> <title>.md
    issues/completed/<NNN> <title>.md

The numeric prefix is the issue's *group*: issues sharing a prefix may be
claimed and worked in parallel, while distinct prefixes stay sequential. The
filename (prefix + title) is the issue's unique identity, so a numeric prefix
alone is ambiguous when a group has more than one member; use the exact
filename in that case. Files are ordered by the integer value of the prefix,
then by filename, never lexicographically.

Every issue also has one canonical git branch, derived deterministically from
its filename: ``issue/<zero-padded id>-<slug>``. The slug is the lowercased
title with every run of non ``[a-z0-9]`` characters replaced by ``-``, leading
and trailing dashes trimmed, capped at 60 characters (trimmed again), and
``issue`` when nothing usable remains. ``branch_for`` resolves an id or exact
filename across **all** states and fails if two issues map to the same branch,
because a branch must identify exactly one issue.

Single-flight applies per prefix: at most one prefix may have issues in
``inprogress``, but every issue sharing that prefix may be claimed at once.
Mutations are no-clobber moves and (when ``fcntl`` is available) hold an
exclusive lock on ``issues/.lock`` so two agents cannot claim work at the same
time. Reads hold a shared lock so they never observe an issue in two states
mid-move.

By default the queue is the **main checkout's** ``issues/`` directory, so every
linked worktree shares one queue. An explicit ``--root`` always overrides it.
Outside a git worktree the default falls back to ``<project>/issues`` beside
``.opencode/``; this script lives in ``.opencode/scripts/``, so its project root
is two levels up. Inside a git worktree a git failure is an error, never a
silent worktree-local queue.

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
import subprocess
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

BRANCH_PREFIX = "issue/"
SLUG_MAX = 60
SLUG_FALLBACK = "issue"
_NON_SLUG = re.compile(r"[^a-z0-9]+")

GIT_TIMEOUT = 5.0


class QueueError(Exception):
    """A domain error (exit code 1), not a usage error."""


def slugify(title: str) -> str:
    """Return the deterministic branch slug for an issue title.

    Lowercase, replace every run of characters outside ``[a-z0-9]`` with ``-``,
    trim dashes, cap at :data:`SLUG_MAX` characters (trimming again), and fall
    back to :data:`SLUG_FALLBACK` when nothing usable remains.
    """
    slug = _NON_SLUG.sub("-", title.lower()).strip("-")
    slug = slug[:SLUG_MAX].rstrip("-")
    return slug or SLUG_FALLBACK


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

    @property
    def branch(self) -> str:
        """Canonical git branch name for this issue (no collision check)."""
        return f"{BRANCH_PREFIX}{self.id}-{slugify(self.title)}"


def _git_output(script_root: Path, *args: str) -> str:
    """Run a bounded, non-interactive git query from ``script_root``."""
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "true"
    env["GCM_INTERACTIVE"] = "never"
    result = subprocess.run(
        ["git", *args],
        cwd=str(script_root),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
        env=env,
    )
    if result.returncode != 0:
        raise OSError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _has_git_marker(path: Path) -> bool:
    """Return whether ``path`` or an ancestor contains a ``.git`` file or dir."""
    current = path.resolve()
    for candidate in (current, *current.parents):
        marker = candidate / ".git"
        if marker.exists() or marker.is_symlink():
            return True
    return False


def _default_root() -> Path:
    """Resolve the main checkout's queue, shared by every linked worktree.

    Inside git, the queue lives beside the repository root that owns the common
    ``.git`` directory. A linked worktree therefore resolves the main
    checkout's ``issues/``; a monorepo subdirectory keeps its own
    ``<subdir>/issues`` relative to that main root. Outside a git worktree the
    queue falls back to ``<project>/issues`` beside ``.opencode/``, but a git
    failure inside one is an error rather than a silent split into a
    worktree-local queue.
    """
    project_root = Path(__file__).resolve().parents[2]
    try:
        top = Path(_git_output(project_root, "rev-parse", "--show-toplevel"))
        common = Path(_git_output(project_root, "rev-parse", "--git-common-dir"))
    except (OSError, subprocess.SubprocessError) as error:
        if _has_git_marker(project_root):
            raise QueueError(
                "could not resolve the main checkout's issue queue: "
                f"{error}; run from a git worktree with git available or pass --root"
            ) from None
        return project_root / "issues"

    if not top.is_absolute():
        top = project_root / top
    if not common.is_absolute():
        common = project_root / common
    top = top.resolve()
    common = common.resolve()

    if common.name != ".git":
        raise QueueError(
            "could not resolve the main checkout's issue queue: "
            f"git common directory is {common}, not a .git directory; "
            "run from a git worktree or pass --root"
        )
    try:
        relative = project_root.relative_to(top)
    except ValueError:
        raise QueueError(
            "could not resolve the main checkout's issue queue: "
            f"{project_root} is not inside the git worktree {top}; pass --root"
        ) from None
    return common.parent / relative / "issues"


def _root(root: Optional[os.PathLike[str] | str]) -> Path:
    return Path(root) if root is not None else _default_root()


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
    seen: dict[str, Issue] = {}

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
            previous = seen.get(entry.name)
            if previous is not None:
                raise QueueError(
                    "duplicate issue filename: "
                    f"{_relpath(previous.path, base)} and "
                    f"{_relpath(issue.path, base)}"
                )
            seen[entry.name] = issue
            issues.append(issue)

    return sorted(issues, key=lambda issue: issue.sort_key)


def scan(root: Optional[os.PathLike[str] | str] = None) -> list[Issue]:
    """Scan every state and return issues ordered by prefix, then filename.

    Same-prefix issues are allowed (they form a parallel group). Raises
    :class:`QueueError` if the exact same filename appears in two states, which
    would make issue identity ambiguous.
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


def _matches(identifier: str, issues: Sequence[Issue]) -> list[Issue]:
    """Resolve ``identifier`` against ``issues``: numeric id or exact filename."""
    identifier = identifier.strip()
    if not identifier:
        raise QueueError("issue id is empty")
    if identifier.isdigit():
        number = int(identifier)
        return [issue for issue in issues if issue.number == number]
    return [issue for issue in issues if issue.filename == identifier]


def _find_unlocked(identifier: str, base: Path) -> Issue:
    issues = _scan_unlocked(base)
    matches = _matches(identifier, issues)
    if not matches:
        raise QueueError(f"issue not found: {identifier.strip()}")
    if len(matches) > 1:
        names = ", ".join(issue.filename for issue in matches)
        raise QueueError(
            f"ambiguous issue id {identifier.strip()!r}: {names}; "
            "use the exact filename"
        )
    return matches[0]


def _find_in_state_unlocked(
    identifier: str,
    expected_state: str,
    base: Path,
    action: Optional[str] = None,
) -> Issue:
    """Resolve an issue that must be in ``expected_state``.

    Numeric ids are matched within the expected state first, so a sibling with
    the same prefix in another state never makes a valid transition ambiguous.
    If several issues share the prefix in the expected state, the caller must
    pass the exact filename.
    """
    issues = _scan_unlocked(base)
    matches = _matches(identifier, issues)
    identifier = identifier.strip()
    in_expected = [issue for issue in matches if issue.state == expected_state]
    suffix = f" for {action}" if action else " for this transition"

    if len(in_expected) == 1:
        return in_expected[0]
    if len(in_expected) > 1:
        names = ", ".join(issue.filename for issue in in_expected)
        raise QueueError(
            f"ambiguous issue id {identifier!r} in {expected_state}: {names}; "
            "use the exact filename"
        )
    if not matches:
        raise QueueError(f"issue not found: {identifier}")

    if len(matches) == 1:
        issue = matches[0]
        raise QueueError(
            f"issue {issue.id} is in {issue.state}, expected {expected_state}{suffix}"
        )
    listing = ", ".join(f"{issue.filename} ({issue.state})" for issue in matches)
    raise QueueError(
        f"issue {identifier!r} is not in {expected_state}{suffix}: {listing}; "
        "use the exact filename"
    )


def _active_prefix_unlocked(issues: Sequence[Issue]) -> Optional[int]:
    """Return the one prefix with ``inprogress`` issues, or ``None``.

    Raises when the queue is corrupt and has in-progress issues from more than
    one prefix. Read-only commands deliberately do not call this so a corrupt
    queue stays inspectable and repairable.
    """
    active = [issue for issue in issues if issue.state == "inprogress"]
    prefixes = sorted({issue.number for issue in active})
    if len(prefixes) > 1:
        names = ", ".join(issue.filename for issue in active)
        raise QueueError(
            f"inprogress issues span multiple prefixes: {names}; "
            "only one prefix may be in progress at a time"
        )
    return prefixes[0] if prefixes else None


def find(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> Issue:
    """Find an issue by numeric id or exact filename.

    A numeric id is ambiguous when several issues share that prefix; use the
    exact filename in that case.
    """
    base = _root(root)
    with _locked(base, shared=True):
        return _find_unlocked(identifier, base)


def _branch_map_unlocked(base: Path) -> dict[str, Issue]:
    """Map every issue's canonical branch to its issue, rejecting collisions."""
    branches: dict[str, Issue] = {}
    for issue in _scan_unlocked(base):
        previous = branches.get(issue.branch)
        if previous is not None:
            raise QueueError(
                f"duplicate issue branch {issue.branch!r}: "
                f"{previous.filename} and {issue.filename}; "
                "rename one issue so each branch is unique"
            )
        branches[issue.branch] = issue
    return branches


def _branch_for_unlocked(identifier: str, base: Path) -> str:
    branches = _branch_map_unlocked(base)
    matches = _matches(identifier, list(branches.values()))
    if not matches:
        raise QueueError(f"issue not found: {identifier.strip()}")
    if len(matches) > 1:
        names = ", ".join(issue.filename for issue in matches)
        raise QueueError(
            f"ambiguous issue id {identifier.strip()!r}: {names}; "
            "use the exact filename"
        )
    return matches[0].branch


def branch_for(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> str:
    """Return the canonical branch for an issue in any state.

    A numeric id is ambiguous when several issues share that prefix; use the
    exact filename in that case. Two issues mapping to the same branch is an
    error, named with both filenames and the branch.
    """
    base = _root(root)
    with _locked(base, shared=True):
        return _branch_for_unlocked(identifier, base)


def next_group(root: Optional[os.PathLike[str] | str] = None) -> list[Issue]:
    """Return the claimable todo prefix group.

    While a prefix is active, only its remaining ``todo`` members are returned
    (possibly none). Otherwise the whole lowest ``todo`` prefix is returned.
    Returns ``[]`` when there is no todo work.
    """
    base = _root(root)
    with _locked(base, shared=True):
        issues = _scan_unlocked(base)
        active_prefix = _active_prefix_unlocked(issues)
        todo = [issue for issue in issues if issue.state == "todo"]
        if active_prefix is not None:
            return [issue for issue in todo if issue.number == active_prefix]
        if not todo:
            return []
        first_prefix = todo[0].number
        return [issue for issue in todo if issue.number == first_prefix]


def next_issue(root: Optional[os.PathLike[str] | str] = None) -> Optional[Issue]:
    """Return the lowest-numbered todo issue, or ``None`` when the queue is empty.

    Informational only: while a prefix group is active the lowest todo issue
    may belong to a later group and is not claimable. Orchestration should use
    :func:`next_group`.
    """
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
        issue = _find_in_state_unlocked(identifier, expected, base)
        destination = _state_dir(base, target) / issue.filename
        return _move_no_clobber(issue.path, destination, base)


def _start(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> Path:
    base = ensure_layout(root)
    with _locked(base):
        issue = _find_in_state_unlocked(identifier, "todo", base, action="start")
        issues = _scan_unlocked(base)
        active_prefix = _active_prefix_unlocked(issues)
        if active_prefix is not None:
            if issue.number != active_prefix:
                active = [member for member in issues if member.state == "inprogress"]
                names = ", ".join(member.filename for member in active)
                raise QueueError(
                    f"prefix {active_prefix:03d} is already in progress: {names}; "
                    "only issues sharing that numeric prefix may start until the "
                    "group is finished"
                )
        else:
            todo = [member for member in issues if member.state == "todo"]
            first = todo[0]
            if issue.number != first.number:
                members = ", ".join(
                    member.filename for member in todo if member.number == first.number
                )
                raise QueueError(
                    f"issue {issue.id} is not next in numeric order: "
                    f"start {first.id} first: {members}"
                )
        destination = _state_dir(base, "inprogress") / issue.filename
        return _move_no_clobber(issue.path, destination, base)


# Public mutation API -------------------------------------------------------


def start(identifier: str, root: Optional[os.PathLike[str] | str] = None) -> Path:
    """Claim a todo issue: todo -> inprogress.

    Single-flight is per numeric prefix: any number of todo issues sharing the
    one active prefix may be claimed, but a later prefix must wait. A numeric
    id is ambiguous when siblings share the prefix; pass the exact filename.
    """
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


_ID_HELP = (
    "numeric prefix (e.g. 001) when unambiguous, or exact filename "
    "such as '001 Fix bug.md'"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manage the issues/ queue: numeric prefix groups in ascending order, "
            "single-flight per prefix (same-prefix issues may run in parallel), "
            "no-clobber moves. Numeric ids are ambiguous when a group has several "
            "members; use the exact filename. Every issue maps to one canonical "
            "git branch issue/<id>-<slug>; 'branch' resolves it across all states "
            "and collisions are an error."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "queue root (default: the main checkout's issues/ directory, shared "
            "by all worktrees; at the project root next to .opencode/ outside "
            "git. Inside a git worktree a git failure is an error; --root "
            "overrides)"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="show counts and issues per state")
    list_parser = subparsers.add_parser("list", help="list issues in one state")
    list_parser.add_argument("state", choices=STATES)
    subparsers.add_parser(
        "next",
        help="show the lowest todo issue (informational; may not be claimable)",
    )
    subparsers.add_parser(
        "next-group",
        help="show every claimable todo issue in the current prefix group",
    )
    branch_parser = subparsers.add_parser(
        "branch",
        help=(
            "print an issue's canonical git branch (issue/<id>-<slug>); resolves "
            "across all states"
        ),
    )
    branch_parser.add_argument("id", help=_ID_HELP)

    for name, help_text in (
        (
            "start",
            "claim a todo issue (todo -> inprogress; same-prefix members may run in parallel)",
        ),
        ("finish", "send an inprogress issue to review (inprogress -> review)"),
        ("complete", "accept a reviewed issue (review -> completed)"),
        ("reopen", "reject a reviewed issue (review -> todo)"),
        ("return", "return an inprogress issue to todo (inprogress -> todo)"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("id", help=_ID_HELP)

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

        if args.command == "next-group":
            group = next_group(root)
            if not group:
                print("none")
            else:
                base = _root(root)
                for issue in group:
                    print(_relpath(issue.path, base))
            return 0

        if args.command == "branch":
            print(branch_for(args.id, root))
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
