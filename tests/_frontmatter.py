"""Minimal YAML frontmatter parser for harness config tests.

Stdlib only (PyYAML is intentionally not a dependency). It parses the subset
used by opencode agent/command files: top-level keys and arbitrarily indented
nested maps whose leaves are scalars. Quoted keys/values and booleans are
handled; lists, anchors, and multiline scalars are not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _scalar(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return value


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Return the frontmatter block of ``text`` as nested dictionaries."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening '---' frontmatter delimiter")
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        raise ValueError("missing closing '---' frontmatter delimiter") from None

    data: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, data)]

    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, separator, value = raw.strip().partition(":")
        if not separator:
            raise ValueError(f"cannot parse frontmatter line: {raw!r}")
        key = _scalar(key)

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"unexpected indentation: {raw!r}")

        parent = stack[-1][1]
        if value.strip():
            parent[key] = _scalar(value)
        else:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))

    return data


def load_frontmatter(path: Path) -> dict[str, Any]:
    """Read ``path`` and parse its frontmatter."""
    return parse_frontmatter(Path(path).read_text(encoding="utf-8"))
