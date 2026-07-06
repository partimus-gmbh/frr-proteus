"""Render proteus-interface objects into 'interface NAME' blocks.

Text source: lib/if.c cli_show_interface / cli_show_interface_desc /
cli_show_interface_end (interfaces are northbound-converted). The
model is deliberately minimal -- it exists mainly as the leafref
target for interface references (see proteus-interface.yang).
"""

from __future__ import annotations

from frr_proteus.render._comments import render_with_comments
from frr_proteus.render._env import env

_template = env.get_template("interfaces.conf.j2")


def render_interfaces(root) -> str:
    """Render all interfaces of a generated ProteusInterface root.

    Returns "" when no interfaces are declared.
    """
    if not root.interface:
        return ""
    return render_with_comments(_template, interfaces=root)
