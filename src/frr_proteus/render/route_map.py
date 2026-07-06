"""Render proteus-route-map objects into 'route-map' blocks.

Route-maps are northbound-converted in FRR (unlike bgpd itself), so
every line the template emits replicates a vty_out in
lib/routemap_cli.c's config-write dispatchers
(route_map_instance_show / route_map_condition_show /
route_map_action_show); bgpd/bgp_routemap.c only contributes the DEFPY
parsers, not the write path. BGP-clause values FRR stores verbatim
(community strings, as-path arguments, ...) render verbatim.
"""

from __future__ import annotations

from frr_proteus.render._comments import render_with_comments
from frr_proteus.render._env import env
from frr_proteus.render._heading import with_heading

_template = env.get_template("route_map.conf.j2")


def render_route_maps(root, *, heading: str | None = "!") -> str:
    """Render all route-maps of a generated ProteusRouteMap root.

    Returns "" when no route-maps are configured. Raises ValueError
    for an entry without an action (mandatory in YANG, but a caller
    may render without validate_tree). `heading` defaults to "!" -- one bare separator line before
    the section; pass a title for a three-line '!' heading instead,
    or None for no prefix at all. Skipped when the section renders
    empty -- see render._heading.
    """
    for rm in root.route_map:
        for entry in rm.entry:
            if not entry.action:
                raise ValueError(
                    f"route-map {rm.name!r} entry {entry.sequence}: "
                    "action (permit|deny) is not set"
                )
    return with_heading(
        heading, render_with_comments(_template, route_maps=root)
    )
