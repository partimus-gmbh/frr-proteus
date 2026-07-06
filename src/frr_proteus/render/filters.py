"""Render proteus-filter objects: prefix lists and access lists.

Text source: lib/filter_cli.c prefix_list_show / access_list_show and
the remark/description variants (the filter library is
northbound-converted). Mind the asymmetry the template replicates:
IPv4 access-lists are written without a leading 'ip' keyword.
"""

from __future__ import annotations

from frr_proteus.render._comments import render_with_comments
from frr_proteus.render._env import env
from frr_proteus.render._heading import with_heading

_template = env.get_template("filters.conf.j2")


def render_filters(root, *, heading: str | None = "!") -> str:
    """Render all prefix-lists and access-lists of a generated
    ProteusFilter root. Returns "" when nothing is configured.

    `heading` defaults to "!" -- one bare separator line before
    the section; pass a title for a three-line '!' heading instead,
    or None for no prefix at all. Skipped when the section renders
    empty -- see render._heading.
    """
    return with_heading(heading, render_with_comments(_template, filters=root))
