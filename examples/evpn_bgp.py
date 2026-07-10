"""Step 2 prototype: build an EVPN VTEP's BGP config -- default instance
(advertise-all-vni, per-VNI RDs/route-targets) plus two L3VPN/EVPN VRF
instances (auto and explicit route-targets, type-5 advertisement) -- as
structured Python data (yang/custom/proteus-bgp*.yang bindings) and
render it to bgpd config text.

Loosely modeled on frr/tests/topotests/bgp_evpn_vxlan_svd_topo1/PE1's
config (not a byte-for-byte copy -- see that topotest for the real
thing). Writes one combined file, out/evpn_frr.conf: FRR's per-daemon
config files are deprecated in favor of one integrated frr.conf, so a
single VTEP's config belongs in one file even though it holds multiple
`router bgp` blocks.

Run with the generated bindings on the path, e.g.:
    PYTHONPATH=src python3 examples/evpn_bgp.py
"""

import ipaddress
import pathlib
import sys
from typing import TypeAlias

sys.path.insert(0, "src")

from frr_proteus._generated.proteus import (
    ProteusBgp,
    ProteusRouteMap,
    validate_tree,
)
from frr_proteus.render import render_bgp_instance, render_route_maps

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "out"

Instance: TypeAlias = ProteusBgp.Instance
EvpnAf: TypeAlias = Instance.AfiSafis.L2vpnEvpn
RouteMap: TypeAlias = ProteusRouteMap.RouteMap


def build_default_instance(*, local_as: int, router_id: str) -> Instance:
    instance = Instance(vrf="default", router_id=router_id)
    instance.autonomous_system.plain = local_as

    neighbor = Instance.Neighbor(address=ipaddress.ip_address("10.30.30.30"))
    neighbor.remote_as.type = "internal"
    neighbor.afi_safis.l2vpn_evpn.activate = True
    # Inbound policy on the EVPN session -- a leafref into
    # /route-maps, so validate_tree checks the map exists.
    neighbor.afi_safis.l2vpn_evpn.filters.route_map_in = "EVPN-IN"
    instance.neighbor.append(neighbor)

    evpn = instance.afi_safis.l2vpn_evpn
    evpn.advertise_all_vni = True
    evpn.advertise_svi_ip = True

    rd_ip = ipaddress.ip_address("10.10.10.10")
    for vni_id in (101, 102):
        vni = EvpnAf.Vni(vni_id=vni_id)
        # RDs and route targets are structured: an explicit RFC 4364 /
        # RFC 4360 encoding with typed components, not "X:NN" strings.
        vni.rd.ipv4.administrator = rd_ip
        vni.rd.ipv4.assigned_number = vni_id
        vni.route_target_import.as2.append(
            EvpnAf.Vni.RouteTargetImport.As2(
                global_admin=65000, local_admin=vni_id
            )
        )
        vni.route_target_export.as2.append(
            EvpnAf.Vni.RouteTargetExport.As2(
                global_admin=65000, local_admin=vni_id
            )
        )
        evpn.vni.append(vni)

    return instance


def build_vrf_instance_auto_rt(*, local_as: int, vrf: str) -> Instance:
    instance = Instance(vrf=vrf)
    instance.autonomous_system.plain = local_as

    evpn = instance.afi_safis.l2vpn_evpn
    # Wildcard RTs (local administrator only) are import-only; the
    # 'auto' sentinel is its own leaf, not a magic list value.
    evpn.route_target_import.wildcard = [300]
    evpn.route_target_import.auto = True

    return instance


def build_vrf_instance_type5(*, local_as: int, vrf: str) -> Instance:
    instance = Instance(vrf=vrf)
    instance.autonomous_system.plain = local_as

    evpn = instance.afi_safis.l2vpn_evpn
    evpn.advertise_ipv4_unicast.enabled = True

    return instance


def build_route_maps() -> ProteusRouteMap:
    root = ProteusRouteMap()
    rmap = RouteMap(name="EVPN-IN")
    entry = RouteMap.Entry(sequence=10, action="permit")
    entry.match.evpn.route_type = "macip"
    rmap.entry.append(entry)
    root.route_map.append(rmap)
    return root


def main() -> None:
    root = ProteusBgp()
    root.instance.append(
        build_default_instance(local_as=65000, router_id="10.10.10.10")
    )
    root.instance.append(
        build_vrf_instance_auto_rt(local_as=65000, vrf="vrf-red")
    )
    root.instance.append(
        build_vrf_instance_type5(local_as=65000, vrf="vrf-purple")
    )
    route_maps = build_route_maps()

    # Whole-tree pass across both module roots: leafref integrity
    # (incl. the neighbor's route-map reference), mandatory leaves,
    # list keys, choice rules -- everything on-assignment validation
    # cannot judge.
    validate_tree(root, route_maps)

    # One combined frr.conf-shaped file: route-maps first, then the
    # router bgp blocks.
    text = render_route_maps(route_maps) + "".join(
        render_bgp_instance(instance) for instance in root.instance
    )

    OUT_DIR.mkdir(exist_ok=True)
    out_file = OUT_DIR / "evpn_frr.conf"
    out_file.write_text(text)
    print(f"--- {out_file} ---")
    print(text, end="")


if __name__ == "__main__":
    main()
