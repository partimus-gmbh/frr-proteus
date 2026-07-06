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


def render_vrfs(
    root,
    *,
    heading: str | None = "!",
    default_l3vni: int | None = None,
    default_l3vni_prefix_routes_only: bool = False,
) -> str:
    """Render all VRF blocks of a generated ProteusVrf root.

    `default_l3vni` optionally carries the DEFAULT VRF's L3VNI, which FRR
    writes as a GLOBAL, unindented top-level ``vni N [prefix-routes-
    only]`` line -- never a ``vrf default`` block (vni_mapping_cmd is
    installed at CONFIG_NODE, zebra_vrf_indent_cli_write emits no indent
    for the default VRF; see vrf.conf.j2 / zebra/zebra_cli.c). It is a
    plain integer (with the boolean `default_l3vni_prefix_routes_only`
    suffix), NOT a data-model node: the default VRF's L3VNI has no
    proteus-vrf node by design, so it is supplied as a scalar. This
    keeps the vni line single-sourced in vrf.conf.j2 and renders before
    the ``vrf NAME`` blocks. The `vni N` line is stock FRR syntax, so
    this stays a purely standard renderer -- it is fed these scalars by
    render.experimental.translate_experimental_to_standard when
    translating an experimental default-VRF origination-l3vni.

    Returns "" when nothing is declared (no VRFs and no default L3VNI).
    `heading` defaults to "!" -- one bare separator line before the
    section; pass a title for a three-line '!' heading instead, or None
    for no prefix at all. Skipped when the section renders empty -- see
    render._heading.
    """
    if not root.vrf and default_l3vni is None:
        return ""
    return with_heading(
        heading,
        render_with_comments(
            _template,
            vrfs=root,
            default_l3vni=default_l3vni,
            default_l3vni_prefix_routes_only=default_l3vni_prefix_routes_only,
        ),
    )
