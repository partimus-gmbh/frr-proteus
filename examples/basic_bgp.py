"""Step 1 prototype: build a two-router eBGP config as structured Python
data (via the typed dataclasses generated from the custom
yang/custom/proteus-bgp.yang model) and render it to bgpd config text.

r1 additionally carries filter objects (an IPv4 prefix-list, a
route-map, a BFD profile) referenced from the neighbor -- exercising
the cross-module leafrefs and the object renderers. Everything renders
into one combined frr.conf-shaped file per router (objects first, then
the router bgp block).

Writes out/r1_frr.conf and out/r2_frr.conf (relative to the repo
root). Run with the generated bindings on the path, e.g.:
    PYTHONPATH=src python3 examples/basic_bgp.py
"""

import pathlib
import sys
from typing import TypeAlias

sys.path.insert(0, "src")

from frr_proteus._generated.proteus import (
    ProteusBfd,
    ProteusBgp,
    ProteusBgpFilter,
    ProteusFilter,
    ProteusInterface,
    ProteusRouteMap,
    annotate,
    validate_tree,
)
from frr_proteus.render import (
    render_bfd,
    render_bgp_instance,
    render_filters,
    render_route_maps,
)

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "out"

Instance: TypeAlias = ProteusBgp.Instance
PrefixList4: TypeAlias = ProteusFilter.PrefixLists.Ipv4.PrefixList
RouteMap: TypeAlias = ProteusRouteMap.RouteMap


class Router:
    """All module roots of one router, validated and rendered together."""

    def __init__(self) -> None:
        self.bgp = ProteusBgp()
        self.route_maps = ProteusRouteMap()
        self.filters = ProteusFilter()
        self.bgp_filters = ProteusBgpFilter()
        self.bfd = ProteusBfd()
        self.interfaces = ProteusInterface()

    def roots(self):
        return (
            self.bgp,
            self.route_maps,
            self.filters,
            self.bgp_filters,
            self.bfd,
            self.interfaces,
        )

    def render(self) -> str:
        # frr.conf composition: objects first (they read naturally
        # before their users), then the router bgp blocks. FRR resolves
        # references by name at load time, so the order is cosmetic.
        return "".join(
            [
                render_filters(self.filters),
                render_route_maps(self.route_maps),
                render_bfd(self.bfd),
                *(
                    render_bgp_instance(instance)
                    for instance in self.bgp.instance
                ),
            ]
        )


def _neighbor(addr: str, remote_as: int | str) -> Instance.Neighbor:
    """One neighbor; remote_as is a plain ASN (int) or one of the
    internal/external/auto relationship keywords (str)."""
    neighbor = Instance.Neighbor(address=addr)
    if isinstance(remote_as, int):
        neighbor.remote_as.plain = remote_as
    else:
        neighbor.remote_as.type = remote_as
    return neighbor


def build_router(
    *,
    local_as: int,
    router_id: str,
    neighbor_addr: str,
    neighbor_remote_as: int | str,
    network: str,
) -> Router:
    router = Router()
    instance = Instance(
        vrf="default", router_id=router_id
    )
    instance.autonomous_system.plain = local_as
    instance.neighbor.append(
        _neighbor(neighbor_addr, neighbor_remote_as)
    )
    instance.afi_safis.ipv4_unicast.network.append(
        Instance.AfiSafis.Ipv4Unicast.Network(prefix=network)
    )
    router.bgp.instance.append(instance)
    return router


def add_import_policy(router: Router) -> None:
    """Give r1 an inbound policy: a prefix-list feeding a route-map, a
    BFD profile on the session -- referenced via leafrefs, so
    validate_tree checks the names resolve."""
    pl = PrefixList4(name="PEER-ROUTES", description="what r2 may send")
    pl.entry.append(
        PrefixList4.Entry(
            sequence=5, action="permit", prefix="198.51.100.0/24", le=32
        )
    )
    router.filters.prefix_lists.ipv4.prefix_list.append(pl)

    rmap = RouteMap(name="FROM-R2")
    entry = RouteMap.Entry(sequence=10, action="permit")
    entry.match.ip_address_prefix_list = "PEER-ROUTES"
    entry.set.local_preference = 200
    rmap.entry.append(entry)
    router.route_maps.route_map.append(rmap)

    router.bfd.profile.append(
        ProteusBfd.Profile(
            name="fast",
            detect_multiplier=3,
            receive_interval=150,
            transmit_interval=150,
        )
    )

    neighbor = router.bgp.instance[0].neighbor[0]
    neighbor.bfd.enabled = True
    neighbor.profile = "fast"
    neighbor.afi_safis.ipv4_unicast.filters.route_map_in = "FROM-R2"
    # RFC 7952 comment annotation (proteus-configuration-metadata.yang):
    # rendered as a full-line '!' comment before the neighbor's lines.
    annotate(neighbor, comment="session to r2, import policy FROM-R2")


def main() -> None:
    r1 = build_router(
        local_as=65001,
        router_id="192.168.255.1",
        neighbor_addr="192.168.255.2",
        neighbor_remote_as="external",
        network="192.0.2.0/24",
    )
    add_import_policy(r1)
    r2 = build_router(
        local_as=65002,
        router_id="192.168.255.2",
        neighbor_addr="192.168.255.1",
        neighbor_remote_as="external",
        network="198.51.100.0/24",
    )

    OUT_DIR.mkdir(exist_ok=True)
    for name, router in [("r1_frr.conf", r1), ("r2_frr.conf", r2)]:
        # Whole-tree pass across ALL module roots: mandatory leaves,
        # list keys, leafrefs (incl. cross-module object references) --
        # everything on-assignment validation cannot judge.
        validate_tree(*router.roots())
        text = router.render()
        (OUT_DIR / name).write_text(text)
        print(f"--- {OUT_DIR / name} ---")
        print(text, end="")


if __name__ == "__main__":
    main()
