"""Render proteus-interface objects into 'interface NAME' blocks.

Text source: lib/if.c cli_show_interface / cli_show_interface_desc /
cli_show_interface_end (interfaces are northbound-converted). The
model is deliberately minimal -- it exists mainly as the leafref
target for interface references (see proteus-interface.yang).
"""

from __future__ import annotations

from frr_proteus.render._comments import render_with_comments
from frr_proteus.render._env import env
from frr_proteus.render._heading import with_heading

_template = env.get_template("interfaces.conf.j2")


def render_interfaces(root, *, heading: str | None = "!") -> str:
    """Render all interfaces of a generated ProteusInterface root.

    Returns "" when no interfaces are declared. `heading` defaults to "!" -- one bare separator line before
    the section; pass a title for a three-line '!' heading instead,
    or None for no prefix at all. Skipped when the section renders
    empty -- see render._heading.
    """
    if not root.interface:
        return ""
    return with_heading(
        heading, render_with_comments(_template, interfaces=root)
    )
