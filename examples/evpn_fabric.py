"""Generate a complete EVPN leaf-spine pod -- 2 spines, 3 leaves, two
tenants -- from one topology table. The all-eBGP design: unnumbered
eBGP underlay on the fabric ports (advertising loopbacks only), eBGP
multihop EVPN overlay between loopbacks, spines passing EVPN routes
through with the next hop unchanged, leaves holding the tenant L2 VNIs
and one VRF instance per tenant L3VNI.

This is the project's pitch in one file: ~5 devices x ~100 lines of
interdependent config from ~120 lines of typed Python, where every
peer-group membership, route-map and prefix-list reference is a
validated leafref and both ends of every session come from the same
table, so they cannot disagree.

Writes one frr.conf-shaped file per device, out/fabric/<name>_frr.conf.
Run with the generated bindings on the path:
    PYTHONPATH=src python3 examples/evpn_fabric.py
"""

import dataclasses
import pathlib
import sys
from typing import TypeAlias

sys.path.insert(0, "src")

from frr_proteus._generated.proteus import (
    ProteusBfd,
    ProteusBgp,
    ProteusFilter,
    ProteusInterface,
    ProteusRouteMap,
    validate_tree,
)
from frr_proteus.render import (
    render_bfd,
    render_bgp_instance,
    render_filters,
    render_interfaces,
    render_route_maps,
)

Instance: TypeAlias = ProteusBgp.Bgp.Instance
RouteMap: TypeAlias = ProteusRouteMap.RouteMaps.RouteMap
PrefixList4: TypeAlias = ProteusFilter.PrefixLists.Ipv4.PrefixList

RT_AS = 65000  # route-target administrator, shared fabric-wide
LOOPBACK_RANGE = "10.90.0.0/24"
TENANTS = {"blue": (4001, [10101, 10102]), "red": (4002, [10201])}


@dataclasses.dataclass
class Device:
    name: str
    asn: int
    loopback: str
    is_spine: bool = False


SPINES = [Device("spine1", 65001, "10.90.0.1", is_spine=True),
          Device("spine2", 65002, "10.90.0.2", is_spine=True)]
LEAVES = [Device(f"leaf{n}", 65100 + n, f"10.90.0.{10 + n}")
          for n in (1, 2, 3)]


def fabric_ports(device: Device) -> list[tuple[str, Device]]:
    """(local port, remote device) pairs: leafN's swp1/swp2 go to
    spine1/spine2, and spineX's swpN goes to leafN -- both ends of
    every link derive from the same rule."""
    if device.is_spine:
        return [(f"swp{n}", leaf) for n, leaf in enumerate(LEAVES, start=1)]
    return [(f"swp{n}", spine) for n, spine in enumerate(SPINES, start=1)]


def build_policy() -> tuple[ProteusFilter, ProteusRouteMap]:
    """Underlay export policy, identical on every device: fabric
    loopbacks and nothing else."""
    filters = ProteusFilter()
    pl = PrefixList4(name="FABRIC-LOOPBACKS")
    pl.entry.append(PrefixList4.Entry(
        sequence=10, action="permit", prefix=LOOPBACK_RANGE, ge=32
    ))
    filters.prefix_lists.ipv4.prefix_list.append(pl)

    rmaps = ProteusRouteMap()
    rmap = RouteMap(name="LOOPBACKS-ONLY")
    permit = RouteMap.Entry(sequence=10, action="permit")
    permit.match.ip_address_prefix_list = "FABRIC-LOOPBACKS"
    rmap.entry.extend([permit, RouteMap.Entry(sequence=65535, action="deny")])
    rmaps.route_maps.route_map.append(rmap)
    return filters, rmaps


def build_bfd() -> ProteusBfd:
    bfd = ProteusBfd()
    bfd.bfd.profile.append(ProteusBfd.Bfd.Profile(
        name="fabric", detect_multiplier=3,
        receive_interval=300, transmit_interval=300,
    ))
    return bfd


def build_interfaces(device: Device) -> ProteusInterface:
    interfaces = ProteusInterface()
    interfaces.interfaces.interface.extend(
        ProteusInterface.Interfaces.Interface(
            name=port, description=f"fabric: {remote.name}"
        )
        for port, remote in fabric_ports(device)
    )
    return interfaces


def build_default_instance(device: Device) -> Instance:
    inst = Instance(
        vrf="default", autonomous_system=device.asn, router_id=device.loopback
    )
    inst.default.ipv4_unicast = False
    inst.bestpath.as_path_multipath_relax.enabled = True

    # Unnumbered eBGP underlay: remote-as external on the group, so
    # members carry nothing but their port.
    underlay = Instance.PeerGroup(name="UNDERLAY", remote_as="external")
    underlay.bfd.enabled = True
    underlay.bfd.profile = "fabric"
    u_af = underlay.afi_safis.ipv4_unicast
    u_af.activate = True
    u_af.filters.route_map_out = "LOOPBACKS-ONLY"
    inst.peer_group.append(underlay)

    # eBGP multihop EVPN overlay between loopbacks; spines relay the
    # routes, so the next hop (the originating VTEP) must survive.
    overlay = Instance.PeerGroup(
        name="OVERLAY", remote_as="external",
        ebgp_multihop=3, update_source=device.loopback,
    )
    overlay.afi_safis.l2vpn_evpn.activate = True
    if device.is_spine:
        overlay.afi_safis.l2vpn_evpn.attribute_unchanged.next_hop = True
    inst.peer_group.append(overlay)

    for port, _remote in fabric_ports(device):
        inst.neighbor.append(Instance.Neighbor(
            address=port, interface_peer=True, v6only=True,
            peer_group="UNDERLAY",
        ))
    overlay_peers = LEAVES if device.is_spine else SPINES
    inst.neighbor.extend(
        Instance.Neighbor(address=peer.loopback, peer_group="OVERLAY",
                          description=peer.name)
        for peer in overlay_peers
    )

    inst.afi_safis.ipv4_unicast.network.append(
        Instance.AfiSafis.Ipv4Unicast.Network(prefix=f"{device.loopback}/32")
    )

    if not device.is_spine:  # leaves are the VTEPs
        evpn = inst.afi_safis.l2vpn_evpn
        evpn.advertise_all_vni = True
        for l3vni, l2vnis in TENANTS.values():
            for vni_id in l2vnis:
                vni = type(evpn).Vni(vni_id=vni_id)
                for rt_set in (vni.route_target_import, vni.route_target_export):
                    rt_set.as2.append(type(rt_set).As2(
                        global_admin=RT_AS, local_admin=vni_id
                    ))
                evpn.vni.append(vni)
    return inst


def build_tenant_instance(device: Device, tenant: str, l3vni: int) -> Instance:
    inst = Instance(vrf=f"vrf-{tenant}", autonomous_system=device.asn,
                    router_id=device.loopback)
    evpn = inst.afi_safis.l2vpn_evpn
    for rt_set in (evpn.route_target_import, evpn.route_target_export):
        rt_set.as2.append(type(rt_set).As2(
            global_admin=RT_AS, local_admin=l3vni
        ))
    evpn.advertise_ipv4_unicast.enabled = True
    return inst


def build_device(device: Device) -> str:
    filters, rmaps = build_policy()
    bfd, interfaces = build_bfd(), build_interfaces(device)
    bgp = ProteusBgp()
    bgp.bgp.instance.append(build_default_instance(device))
    if not device.is_spine:
        bgp.bgp.instance.extend(
            build_tenant_instance(device, tenant, l3vni)
            for tenant, (l3vni, _) in TENANTS.items()
        )
    validate_tree(bgp, rmaps, filters, bfd, interfaces)
    return (
        render_interfaces(interfaces)
        + render_filters(filters)
        + render_route_maps(rmaps)
        + render_bfd(bfd)
        + "".join(render_bgp_instance(i) for i in bgp.bgp.instance)
    )


def main() -> None:
    out = pathlib.Path(__file__).resolve().parent.parent / "out" / "fabric"
    out.mkdir(parents=True, exist_ok=True)
    for device in [*SPINES, *LEAVES]:
        path = out / f"{device.name}_frr.conf"
        path.write_text(build_device(device))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
