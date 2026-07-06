"""Section separators and opt-in headings for composed frr.conf files.

FRR only has whole-line comments ('!' or '#' as the first
non-whitespace char -- see render/_comments.py), so sections are set
apart with '!' comment lines. Every render_* function takes a
``heading`` keyword with three behaviours:

- default ``"!"``: one bare '!' separator line before the section, so
  adjacent sections never run together;
- a title: a three-line heading block instead --

      !
      ! route-maps
      !

  Since the block itself starts and ends with '!', swapping the
  default separator for it never doubles up separator lines;
- ``None``: nothing at all (e.g. for the very first section of a
  file, or callers doing their own separation).

Either way the prefix is skipped when the section renders empty.
Titles are free-form, so one object type can be split into several
titled sections (e.g. multiple prefix-list sections rendered from
separate ProteusFilter roots); heading() is the standalone builder.
"""

from __future__ import annotations


def heading(title: str) -> str:
    """Return a three-line '!' comment heading for `title`.

    Multi-line titles get one '! ' comment line per non-empty line,
    still framed by the bare '!' pair.
    """
    lines = [line.strip() for line in title.splitlines()]
    body = "".join(f"! {line}\n" for line in lines if line)
    if not body:
        raise ValueError("heading title is empty")
    return f"!\n{body}!\n"


def with_heading(title: str | None, body: str) -> str:
    """Prefix `body` per the ``heading`` contract above: "!" (the
    render_* default) prefixes one bare separator line, any other
    title a heading() block. No-op when `title` is None or `body` is
    empty (an empty section gets no separator/heading)."""
    if title is None or not body:
        return body
    if title == "!":
        return "!\n" + body
    return heading(title) + body
