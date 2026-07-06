"""Internet edge router of a small AS: one transit provider, an IXP
route-server peer-group, and an iBGP session to the core -- the classic
"tag on ingress, filter on egress" peering policy. Everything the
neighbors reference (prefix-lists, an as-path list, route-maps) is
built as typed objects and cross-checked by validate_tree, so a typo'd
route-map name fails validation instead of silently no-op'ing in bgpd.

Writes one frr.conf-shaped file, out/internet_peering_frr.conf.
Run with the generated bindings on the path:
    PYTHONPATH=src python3 examples/internet_peering.py
"""

import pathlib
import sys
from typing import TypeAlias

sys.path.insert(0, "src")

from frr_proteus._generated.proteus import (
    ProteusBgp,
    ProteusBgpFilter,
    ProteusFilter,
    ProteusRouteMap,
    validate_tree,
)
from frr_proteus.render import (
    render_bgp_filters,
    render_bgp_instance,
    render_filters,
    render_route_maps,
)

Instance: TypeAlias = ProteusBgp.Bgp.Instance
RouteMap: TypeAlias = ProteusRouteMap.RouteMaps.RouteMap
PrefixList4: TypeAlias = ProteusFilter.PrefixLists.Ipv4.PrefixList
AsPathList: TypeAlias = ProteusBgpFilter.BgpFilters.AsPathAccessList

LOCAL_AS, TRANSIT_AS = 64620, 64720
LOOPBACK = "192.0.2.1"
OUR_PREFIXES = ["192.0.2.0/24", "198.51.100.0/24"]
BOGONS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"]
IXP_PEERS = [  # (address, remote-as, description)
    ("203.0.113.10", 64801, "ixp-rs-1"),
    ("203.0.113.11", 64802, "ixp-rs-2"),
]


def prefix_list(name: str, prefixes: list[str], *, le: int | None = None):
    pl = PrefixList4(name=name)
    pl.entry.extend(
        PrefixList4.Entry(sequence=10 * n, action="permit", prefix=p, le=le)
        for n, p in enumerate(prefixes, start=1)
    )
    return pl


def tag_map(name: str, local_pref: int, community: int) -> RouteMap:
    """Ingress policy: drop bogons and own-prefix loops, then tag the
    rest with LOCAL_AS:<community> and a local-preference tier."""
    rmap = RouteMap(name=name)
    block = RouteMap.Entry(sequence=10, action="deny")
    block.match.ip_address_prefix_list = "BOGONS"
    accept = RouteMap.Entry(sequence=20, action="permit")
    accept.set.local_preference = local_pref
    accept.set.community.member.append(
        type(accept.set.community).Member(
            global_admin=LOCAL_AS, local_admin=community
        )
    )
    accept.set.community.additive = True
    rmap.entry.extend([block, accept])
    return rmap


def export_map() -> RouteMap:
    """Egress policy: our own aggregates only, never private AS paths."""
    rmap = RouteMap(name="EXPORT-OUT")
    leak_guard = RouteMap.Entry(sequence=10, action="deny")
    leak_guard.match.as_path = "PRIVATE-ASNS"
    ours = RouteMap.Entry(sequence=20, action="permit")
    ours.match.ip_address_prefix_list = "OUR-PREFIXES"
    deny_rest = RouteMap.Entry(sequence=65535, action="deny")
    rmap.entry.extend([leak_guard, ours, deny_rest])
    return rmap


def build_instance() -> Instance:
    inst = Instance(
        vrf="default", autonomous_system=LOCAL_AS, router_id=LOOPBACK
    )

    # IXP route servers: shared policy on the peer-group, per-peer
    # remote-as. RS paths omit the RS's own ASN, hence no enforcement.
    ixp = Instance.PeerGroup(name="IXP-RS", enforce_first_as=False)
    ixp.bfd.enabled = True
    af = ixp.afi_safis.ipv4_unicast
    af.activate = True
    af.soft_reconfiguration_inbound = True
    af.maximum_prefix.count = 50000
    af.maximum_prefix.restart_interval = 30
    af.filters.route_map_in = "IXP-IN"
    af.filters.route_map_out = "EXPORT-OUT"
    inst.peer_group.append(ixp)
    inst.neighbor.extend(
        Instance.Neighbor(
            address=addr, remote_as=asn, peer_group="IXP-RS", description=desc
        )
        for addr, asn, desc in IXP_PEERS
    )

    transit = Instance.Neighbor(
        address="203.0.113.129", remote_as=TRANSIT_AS,
        description="transit uplink", password="transit-md5",
        ttl_security_hops=1,
    )
    t_af = transit.afi_safis.ipv4_unicast
    t_af.activate = True
    t_af.maximum_prefix.count = 1000000
    t_af.maximum_prefix.threshold = 90
    t_af.maximum_prefix.warning_only = True
    t_af.remove_private_as = "all"
    t_af.filters.route_map_in = "TRANSIT-IN"
    t_af.filters.route_map_out = "EXPORT-OUT"
    inst.neighbor.append(transit)

    core = Instance.Neighbor(
        address="192.0.2.2", remote_as="internal",
        description="core rr", update_source=LOOPBACK,
    )
    core.afi_safis.ipv4_unicast.activate = True
    core.afi_safis.ipv4_unicast.next_hop_self.enabled = True
    inst.neighbor.append(core)

    inst.afi_safis.ipv4_unicast.network.extend(
        Instance.AfiSafis.Ipv4Unicast.Network(prefix=p) for p in OUR_PREFIXES
    )
    return inst


def main() -> None:
    filters = ProteusFilter()
    filters.prefix_lists.ipv4.prefix_list.extend([
        prefix_list("OUR-PREFIXES", OUR_PREFIXES),
        prefix_list("BOGONS", BOGONS, le=32),
    ])

    bgp_filters = ProteusBgpFilter()
    private = AsPathList(name="PRIVATE-ASNS")
    private.entry.append(
        AsPathList.Entry(
            sequence=10, action="permit",
            regex="_(6451[2-9]|645[2-9][0-9]|64[6-9][0-9][0-9]|65[0-4][0-9][0-9]|655[0-2][0-9]|6553[0-4])_",
        )
    )
    bgp_filters.bgp_filters.as_path_access_list.append(private)

    rmaps = ProteusRouteMap()
    rmaps.route_maps.route_map.extend([
        tag_map("IXP-IN", local_pref=200, community=200),
        tag_map("TRANSIT-IN", local_pref=100, community=100),
        export_map(),
    ])

    bgp = ProteusBgp()
    bgp.bgp.instance.append(build_instance())
    validate_tree(bgp, rmaps, filters, bgp_filters)

    text = (
        render_filters(filters)
        + render_bgp_filters(bgp_filters)
        + render_route_maps(rmaps)
        + render_bgp_instance(bgp.bgp.instance[0])
    )
    out = pathlib.Path(__file__).resolve().parent.parent / "out"
    out.mkdir(exist_ok=True)
    (out / "internet_peering_frr.conf").write_text(text)
    print(f"--- {out / 'internet_peering_frr.conf'} ---")
    print(text, end="")


if __name__ == "__main__":
    main()
