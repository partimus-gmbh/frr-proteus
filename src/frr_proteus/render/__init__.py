"""Renderers composing the generated proteus bindings into frr.conf
text. Each render_* function returns one section (or "" when its root
holds no config); callers concatenate them into a single integrated
frr.conf.

Recommended section order is dependency-first -- referenced objects
before their consumers (FRR itself needs this in some cases, and it
reads logically top-down either way):

    system, vrfs, interfaces, bfd profiles,
    prefix-/access-lists (render_filters),
    as-path/community lists (render_bgp_filters),
    route-maps, bgp process, router bgp instances, evpn global

Every render_* function takes a ``heading=`` keyword. Its default
"!" prefixes one bare '!' separator line, so adjacent sections never
run together; a title renders a three-line '!' comment heading
instead (which starts and ends with '!' itself, so it never doubles
up with the default separator); None disables the prefix. Either way
it is skipped when the section renders empty. heading() is the
standalone builder for free-form composition (e.g. several
separately titled prefix-list sections rendered from separate
ProteusFilter roots); it emits only the opening separator + title
lines -- the following section's default leading separator completes
the block, so ``heading("bgp") + render_bgp_instance(...)`` never
doubles a '!' line.
"""

from frr_proteus.render._heading import heading
from frr_proteus.render.bfd import render_bfd
from frr_proteus.render.bgp import (
    render_bgp_instance,
    render_bgp_process,
)
from frr_proteus.render.bgp_filters import render_bgp_filters
from frr_proteus.render.experimental import (
    EvpnTranslationWarning,
    StandardTranslation,
    render_experimental_bgp_instance,
    render_experimental_evpn_global,
    translate_experimental_to_standard,
)
from frr_proteus.render.filters import render_filters
from frr_proteus.render.interfaces import render_interfaces
from frr_proteus.render.route_map import render_route_maps
from frr_proteus.render.system import render_system
from frr_proteus.render.vrf import render_vrfs

__all__ = [
    "EvpnTranslationWarning",
    "StandardTranslation",
    "heading",
    "render_bfd",
    "render_bgp_filters",
    "render_bgp_instance",
    "render_bgp_process",
    "render_experimental_bgp_instance",
    "render_experimental_evpn_global",
    "render_filters",
    "render_interfaces",
    "render_route_maps",
    "render_system",
    "render_vrfs",
    "translate_experimental_to_standard",
]
