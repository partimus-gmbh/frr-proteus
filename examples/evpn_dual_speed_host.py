"""Reproduce a real-world EVPN compute host (anonymized): a Proxmox-style
VTEP with a dual-speed BGP underlay -- two 100G and two 25G unnumbered
uplinks to the same spine pair -- where per-loopback large communities
steer which loopback is reachable over which link speed. An eBGP
multihop overlay between loopbacks carries EVPN, with L2 VNIs in the
default instance and three tenant VRFs holding their L3VNI route
targets.

Reproduction notes vs. the original running config:
  - AS numbers, addresses, names and passwords are anonymized. Like
    the original ('router bgp 64505.101 as-notation dot'), the ASNs
    are written in dotted notation -- structured as two uint16
    halves per pt:as-number-notation, rendered '<high>.<low>' --
    with 'as-notation dot' set on every instance (a display-only
    knob for later show output).
  - 'frr defaults', hostname/log/vtysh service lines, 'vrf ... vni'
    blocks and interface 'ipv6 nd ra-interval' are zebra/vtysh
    surface, but common enough in the real world that minimal proteus
    modules model exactly these lines (proteus-system, proteus-vrf,
    and the ipv6-nd knob on proteus-interface).

Run with the generated bindings on the path:
    PYTHONPATH=src python3 examples/evpn_dual_speed_host.py
"""

import pathlib
import sys
from typing import TypeAlias

sys.path.insert(0, "src")

from frr_proteus._generated.proteus import (
    ProteusBgp,
    ProteusBgpFilter,
    ProteusFilter,
    ProteusInterface,
    ProteusRouteMap,
    ProteusSystem,
    ProteusVrf,
    validate_tree,
)
from frr_proteus.render import (
    render_bgp_filters,
    render_bgp_instance,
    render_filters,
    render_interfaces,
    render_route_maps,
    render_system,
    render_vrfs,
)

Instance: TypeAlias = ProteusBgp.Bgp.Instance
RouteMap: TypeAlias = ProteusRouteMap.RouteMaps.RouteMap
PrefixList4: TypeAlias = ProteusFilter.PrefixLists.Ipv4.PrefixList
LargeCommunityList: TypeAlias = (
    ProteusBgpFilter.BgpFilters.LargeCommunityList
)

# Dotted (asdot) notation, as in the original config, structured as
# (high, low) halves: 64506.101 is ASN 64506 * 65536 + 101. Rendered
# '<high>.<low>'; 'as-notation dot' below only tells FRR to format
# show output the same way.
HOST_AS, SPINE_AS = (64506, 101), {1: (64506, 11), 2: (64506, 12)}
RT_AS, LC_AS = 65099, 4210000000  # route-target admin / community admin

# One loopback per reachability class: (role, address, LC local-data-2).
# The large community LC_AS:1:N tags each class end-to-end; the four
# route-maps below are all derived from this one table.
LOOPBACKS = [
    ("PRIMARY", "10.44.8.21", 1),
    ("25G-PREFERRED", "10.44.9.21", 2),
    ("100G-ONLY", "10.44.10.21", 3),
    ("25G-ONLY", "10.44.11.21", 4),
]
ROUTER_ID = LOOPBACKS[0][1]

SPINE_NEIGHBORS = [  # (spine number, overlay address, underlay interfaces)
    (1, "10.44.4.1", ["cx100g_p1", "e25g_top_p4"]),
    (2, "10.44.4.2", ["cx100g_p2", "e25g_bot_p4"]),
]
UPLINKS_100G = ["cx100g_p1", "cx100g_p2"]

# Tenant VRFs: name -> L3VNI (the shared export RT_AS:15000000 marks
# routes every tenant may import).
VRFS = {"tnt_25G01": 15000001, "tnt_100G01": 15000002, "tnt_25GP01": 15000003}
L2_VNIS = [15000004, 15000005, 15000006, 16001101, 16001102, 16001103]
DEFAULT_INSTANCE_RT = 16001100


def build_host_objects() -> tuple[ProteusSystem, ProteusVrf, ProteusInterface]:
    """The zebra/vtysh-side lines that used to ride along as a literal
    preamble: global host settings, the VRF-to-L3VNI mappings, and the
    RA interval on every underlay port (RAs are how unnumbered eBGP
    learns the peer's link-local next hop)."""
    system = ProteusSystem()
    system.system.frr_defaults = "datacenter"
    system.system.hostname = "vtep-host-01"
    system.system.log.syslog = "informational"
    system.system.service.integrated_vtysh_config = True

    vrfs = ProteusVrf()
    vrfs.vrfs.vrf.extend(
        ProteusVrf.Vrfs.Vrf(name=vrf, l3vni=vni) for vrf, vni in VRFS.items()
    )

    interfaces = ProteusInterface()
    for _, _, ifaces in SPINE_NEIGHBORS:
        for ifname in ifaces:
            intf = ProteusInterface.Interfaces.Interface(name=ifname)
            intf.ipv6_nd.ra_interval = 5
            interfaces.interfaces.interface.append(intf)
    return system, vrfs, interfaces


def rm_entry(seq, action="permit", desc=None, **clauses) -> RouteMap.Entry:
    """One route-map entry from keyword clauses -- the schema is typed,
    so each clause is a plain attribute assignment."""
    e = RouteMap.Entry(sequence=seq, action=action, description=desc)
    if pl := clauses.get("match_pl"):
        e.match.ip_address_prefix_list = pl
    if lc := clauses.get("match_lc"):
        e.match.large_community.list_name = lc
    if set_lc := clauses.get("set_lc"):
        ga, ld1, ld2 = set_lc
        e.set.large_community.member.append(
            type(e.set.large_community).Member(
                global_admin=ga, local_data_1=ld1, local_data_2=ld2
            )
        )
    if (add := clauses.get("metric_add")) is not None:
        e.set.metric.operation = "add"  # 'set metric +N': raise MED
        e.set.metric.value = add
    if weight := clauses.get("set_weight"):
        e.set.weight = weight
    if call := clauses.get("call"):
        e.call, e.on_match = call, "next"
    return e


def build_policy_objects() -> tuple[ProteusFilter, ProteusBgpFilter, ProteusRouteMap]:
    """Per-loopback prefix-lists and large-community lists, plus the
    four underlay steering route-maps -- all generated from LOOPBACKS."""
    filters, bgp_filters, rmaps = ProteusFilter(), ProteusBgpFilter(), ProteusRouteMap()

    for role, addr, ld2 in LOOPBACKS:
        pl = PrefixList4(name=f"LOOPBACK-{role}")
        pl.entry.append(
            PrefixList4.Entry(sequence=10, action="permit", prefix=f"{addr}/32")
        )
        filters.prefix_lists.ipv4.prefix_list.append(pl)

        lcl = LargeCommunityList(name=f"LOOPBACK-{role}", type="standard")
        entry = LargeCommunityList.Entry(sequence=10, action="permit")
        entry.large_communities.member.append(
            LargeCommunityList.Entry.LargeCommunities.Member(
                global_admin=LC_AS, local_data_1=1, local_data_2=ld2
            )
        )
        lcl.entry.append(entry)
        bgp_filters.bgp_filters.large_community_list.append(lcl)

    tagger = RouteMap(name="ATTACH-COMMUNITIES-TO-EXPORT-PREFIXES")
    tagger.entry.extend(
        rm_entry(10 * n, match_pl=f"LOOPBACK-{role}", set_lc=(LC_AS, 1, ld2))
        for n, (role, _, ld2) in enumerate(LOOPBACKS, start=1)
    )

    # Steering: the 100G links never carry the 25G-ONLY loopback and
    # de-prefer the 25G-PREFERRED one; the 25G links are the mirror
    # image. Outbound maps first call the tagger, inbound maps filter
    # and weight what the spines send back.
    in_100g = RouteMap(name="SPINES-UNDERLAY-100G-IN")
    in_100g.entry.extend([
        rm_entry(20, desc="Allow Primary Loopback", match_lc="LOOPBACK-PRIMARY"),
        rm_entry(30, desc="Allow 25G-PREFERRED route", match_lc="LOOPBACK-25G-PREFERRED"),
        rm_entry(40, desc="Allow 100G-ONLY routes", match_lc="LOOPBACK-100G-ONLY"),
        rm_entry(50, "deny", desc="Deny 25G-ONLY routes", match_lc="LOOPBACK-25G-ONLY"),
        rm_entry(65535, desc="Default Permit"),
    ])
    out_100g = RouteMap(name="SPINES-UNDERLAY-100G-OUT")
    out_100g.entry.extend([
        rm_entry(10, call="ATTACH-COMMUNITIES-TO-EXPORT-PREFIXES"),
        rm_entry(20, desc="Allow Primary Loopback", match_lc="LOOPBACK-PRIMARY"),
        rm_entry(30, desc="Make 25G-PREFERRED route on 100G link less preferred by increasing MED",
                 match_lc="LOOPBACK-25G-PREFERRED", metric_add=100),
        rm_entry(40, desc="Allow 100G-ONLY Prefix", match_lc="LOOPBACK-100G-ONLY"),
        rm_entry(65535, "deny"),
    ])
    in_25g = RouteMap(name="SPINES-UNDERLAY-25G-IN")
    in_25g.entry.extend([
        rm_entry(20, desc="Allow Primary Loopback", match_lc="LOOPBACK-PRIMARY"),
        rm_entry(30, desc="Make 25G-PREFERRED routes preferred (egress over 25G)",
                 match_lc="LOOPBACK-25G-PREFERRED", set_weight=100),
        rm_entry(40, "deny", desc="Deny 100G-ONLY routes", match_lc="LOOPBACK-100G-ONLY"),
        rm_entry(50, desc="Allow 25G-ONLY routes", match_lc="LOOPBACK-25G-ONLY"),
        rm_entry(65535, desc="Default Permit"),
    ])
    out_25g = RouteMap(name="SPINES-UNDERLAY-25G-OUT")
    out_25g.entry.extend([
        rm_entry(10, call="ATTACH-COMMUNITIES-TO-EXPORT-PREFIXES"),
        rm_entry(20, desc="Allow Primary Loopback", match_lc="LOOPBACK-PRIMARY"),
        rm_entry(30, desc="Allow 25G-PREFERRED route on 25G link",
                 match_lc="LOOPBACK-25G-PREFERRED"),
        rm_entry(40, desc="Allow 25G-ONLY Prefix on 25G link", match_lc="LOOPBACK-25G-ONLY"),
        rm_entry(65535, "deny"),
    ])
    rmaps.route_maps.route_map.extend([tagger, in_100g, out_100g, in_25g, out_25g])
    return filters, bgp_filters, rmaps


def set_asdot(asn_node, halves: tuple[int, int]) -> None:
    """Fill a pt:as-number-notation node's asdot case from (high, low)."""
    asn_node.asdot.high, asn_node.asdot.low = halves


def add_rts(rt_set, *values: int) -> None:
    """Append RT_AS:<value> route targets (2-byte-AS encoding)."""
    rt_set.as2.extend(
        type(rt_set).As2(global_admin=RT_AS, local_admin=v) for v in values
    )


def build_default_instance() -> Instance:
    inst = Instance(vrf="default", as_notation="dot", router_id=ROUTER_ID)
    set_asdot(inst.autonomous_system, HOST_AS)
    inst.default.ipv4_unicast = False
    inst.deterministic_med = False
    inst.graceful_restart.mode = "disable"
    inst.bestpath.as_path_multipath_relax.enabled = True

    # Peer-groups hold everything shared; members add remote-as,
    # description and (for the underlay) the physical port.
    overlay = Instance.PeerGroup(
        name="SPINES-OVERLAY", password="anon-overlay-pw",
        ebgp_multihop=3, update_source=ROUTER_ID,
    )
    overlay.bfd.enabled = True
    overlay.afi_safis.l2vpn_evpn.activate = True
    overlay.afi_safis.l2vpn_evpn.soft_reconfiguration_inbound = True
    inst.peer_group.append(overlay)

    for speed in ("100G", "25G"):
        pg = Instance.PeerGroup(
            name=f"SPINES-UNDERLAY-{speed}", password="anon-underlay-pw"
        )
        pg.bfd.enabled = True
        af = pg.afi_safis.ipv4_unicast
        af.activate = True
        af.soft_reconfiguration_inbound = True
        af.filters.route_map_in = f"SPINES-UNDERLAY-{speed}-IN"
        af.filters.route_map_out = f"SPINES-UNDERLAY-{speed}-OUT"
        inst.peer_group.append(pg)

    for spine, overlay_addr, ifaces in SPINE_NEIGHBORS:
        overlay_peer = Instance.Neighbor(
            address=overlay_addr, peer_group="SPINES-OVERLAY",
            description=f"anon-spine-{spine}",
        )
        set_asdot(overlay_peer.remote_as, SPINE_AS[spine])
        inst.neighbor.append(overlay_peer)
        for ifname in ifaces:
            speed = "100G" if ifname in UPLINKS_100G else "25G"
            underlay_peer = Instance.Neighbor(
                address=ifname, interface_peer=True, v6only=True,
                peer_group=f"SPINES-UNDERLAY-{speed}",
                description=f"anon-spine-{spine}",
            )
            set_asdot(underlay_peer.remote_as, SPINE_AS[spine])
            inst.neighbor.append(underlay_peer)

    inst.afi_safis.ipv4_unicast.network.extend(
        Instance.AfiSafis.Ipv4Unicast.Network(prefix=f"{addr}/32")
        for _, addr, _ in LOOPBACKS
    )

    evpn = inst.afi_safis.l2vpn_evpn
    evpn.advertise_all_vni = True
    evpn.advertise_svi_ip = True
    for vni_id in L2_VNIS:
        vni = type(evpn).Vni(vni_id=vni_id)
        add_rts(vni.route_target_import, vni_id)
        add_rts(vni.route_target_export, vni_id)
        evpn.vni.append(vni)
    add_rts(evpn.route_target_import, DEFAULT_INSTANCE_RT)
    add_rts(evpn.route_target_export, DEFAULT_INSTANCE_RT)
    return inst


def build_vrf_instance(vrf: str, l3vni: int) -> Instance:
    inst = Instance(vrf=vrf, as_notation="dot", router_id=ROUTER_ID)
    set_asdot(inst.autonomous_system, HOST_AS)
    inst.deterministic_med = False
    evpn = inst.afi_safis.l2vpn_evpn
    add_rts(evpn.route_target_import, l3vni)
    add_rts(evpn.route_target_export, 15000000, l3vni)  # shared + own RT
    return inst


def main() -> None:
    system, vrfs, interfaces = build_host_objects()
    filters, bgp_filters, rmaps = build_policy_objects()
    bgp = ProteusBgp()
    bgp.bgp.instance.append(build_default_instance())
    bgp.bgp.instance.extend(
        build_vrf_instance(vrf, vni) for vrf, vni in VRFS.items()
    )
    validate_tree(bgp, rmaps, filters, bgp_filters, system, vrfs, interfaces)

    text = (
        render_system(system)
        + render_vrfs(vrfs)
        + render_interfaces(interfaces)
        + render_filters(filters)
        + render_route_maps(rmaps)
        + "".join(render_bgp_instance(i) for i in bgp.bgp.instance)
        + render_bgp_filters(bgp_filters)
    )
    out = pathlib.Path(__file__).resolve().parent.parent / "out"
    out.mkdir(exist_ok=True)
    (out / "evpn_dual_speed_host_frr.conf").write_text(text)
    print(f"--- {out / 'evpn_dual_speed_host_frr.conf'} ---")
    print(text, end="")


if __name__ == "__main__":
    main()
