"""Render proteus-filter objects: prefix lists and access lists.

Text source: lib/filter_cli.c prefix_list_show / access_list_show and
the remark/description variants (the filter library is
northbound-converted). Mind the asymmetry the template replicates:
IPv4 access-lists are written without a leading 'ip' keyword.
"""

from __future__ import annotations

from frr_proteus.render._env import env

_template = env.get_template("filters.conf.j2")


def render_filters(root) -> str:
    """Render all prefix-lists and access-lists of a generated
    ProteusFilter root. Returns "" when nothing is configured.
    """
    return _template.render(filters=root)
