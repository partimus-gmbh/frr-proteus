"""Render proteus-bfd profiles into the 'bfd' config block.

Text source: bfdd/bfdd_cli.c's cli_show callbacks (bfdd is
northbound-converted): ' profile NAME' with two-space-indented leaves,
' exit' per profile, 'exit' closing the block. Intervals are modeled
in milliseconds, matching the CLI (FRR's own YANG stores microseconds
and divides by 1000 on write).
"""

from __future__ import annotations

from frr_proteus.render._comments import render_with_comments
from frr_proteus.render._env import env
from frr_proteus.render._heading import with_heading

_template = env.get_template("bfd.conf.j2")


def render_bfd(root, *, heading: str | None = "!") -> str:
    """Render the 'bfd' block of a generated ProteusBfd root.

    Returns "" when no profiles are configured (an empty 'bfd'/'exit'
    pair would be pointless, if harmless). `heading` defaults to "!" -- one bare separator line before
    the section; pass a title for a three-line '!' heading instead,
    or None for no prefix at all. Skipped when the section renders
    empty -- see render._heading.
    """
    if not root.profile:
        return ""
    return with_heading(heading, render_with_comments(_template, bfd=root))
