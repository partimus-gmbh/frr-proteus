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

- ``None``: nothing at all (e.g. for callers doing their own
  separation).

Either way the prefix is skipped when the section renders empty.

The standalone heading() builder deliberately emits only the OPENING
separator and title lines -- the closing '!' comes from whatever
renders next (its default leading separator) -- so free-form
composition like ``heading("bgp") + render_bgp_instance(...)``
produces exactly the three-line block with no doubled '!' and no
deduplication anywhere. Titles are free-form, so one object type can
be split into several titled sections (e.g. multiple prefix-list
sections rendered from separate ProteusFilter roots).
"""

from __future__ import annotations


def heading(title: str) -> str:
    """Return the opening '!' separator plus '! <line>' comment
    line(s) for `title` (one per non-empty title line).

    No closing '!' -- concatenate a render_* call with the default
    ``heading="!"`` after it and the section's leading separator
    completes the three-line block.
    """
    lines = [line.strip() for line in title.splitlines()]
    body = "".join(f"! {line}\n" for line in lines if line)
    if not body:
        raise ValueError("heading title is empty")
    return f"!\n{body}"


def with_heading(title: str | None, body: str) -> str:
    """Prefix `body` per the ``heading`` contract above: "!" (the
    render_* default) prefixes one bare separator line, any other
    title the full three-line heading block. No-op when `title` is
    None or `body` is empty (an empty section gets no separator or
    heading)."""
    if title is None or not body:
        return body
    if title == "!":
        return "!\n" + body
    return heading(title) + "!\n" + body
