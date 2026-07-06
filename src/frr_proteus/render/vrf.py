"""Render proteus-vrf objects into 'vrf NAME' blocks.

Text source: lib/vrf.c lib_vrf_cli_write / lib_vrf_cli_write_end for
the block itself, zebra/zebra_cli.c vni_mapping_cmd /
lib_vrf_zebra_l3vni_id_cli_write for the L3VNI mapping line. The model
is deliberately minimal -- see proteus-vrf.yang.
"""

from __future__ import annotations

from frr_proteus.render._env import env

_template = env.get_template("vrf.conf.j2")


def render_vrfs(root) -> str:
    """Render all VRF blocks of a generated ProteusVrf root.

    Returns "" when no VRFs are declared.
    """
    if not root.vrfs.vrf:
        return ""
    return _template.render(vrfs=root.vrfs)
