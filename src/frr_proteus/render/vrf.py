"""Render proteus-vrf objects into 'vrf NAME' blocks.

Text source: lib/vrf.c lib_vrf_cli_write / lib_vrf_cli_write_end for
the block itself, zebra/zebra_cli.c vni_mapping_cmd /
lib_vrf_zebra_l3vni_id_cli_write for the L3VNI mapping line. The model
is deliberately minimal -- see proteus-vrf.yang.
"""

from __future__ import annotations

from frr_proteus.render._comments import render_with_comments
from frr_proteus.render._env import env
from frr_proteus.render._heading import with_heading

_template = env.get_template("vrf.conf.j2")


def render_vrfs(root, *, heading: str | None = "!") -> str:
    """Render all VRF blocks of a generated ProteusVrf root.

    Returns "" when no VRFs are declared. `heading` defaults to "!" -- one bare separator line before
    the section; pass a title for a three-line '!' heading instead,
    or None for no prefix at all. Skipped when the section renders
    empty -- see render._heading.
    """
    if not root.vrf:
        return ""
    return with_heading(heading, render_with_comments(_template, vrfs=root))
