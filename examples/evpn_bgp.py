"""Step 2 prototype: build an EVPN VTEP's BGP config -- default instance
(advertise-all-vni, per-VNI RDs/route-targets) plus two L3VPN/EVPN VRF
instances (auto and explicit route-targets, type-5 advertisement) -- as
structured Python data and render it to bgpd config text.

Loosely modeled on frr/tests/topotests/bgp_evpn_vxlan_svd_topo1/PE1's
config (not a byte-for-byte copy -- see that topotest for the real
thing). Writes one combined file, out/evpn_frr.conf: FRR's per-daemon
config files are deprecated in favor of one integrated frr.conf, so a
single VTEP's config belongs in one file even though it holds multiple
`router bgp` blocks.

Run with the generated bindings on the path, e.g.:
    PYTHONPATH=src python3 examples/evpn_bgp.py
"""

import pathlib
import sys

sys.path.insert(0, "src")

from frr_proteus._generated.frr_bgp import FrrRouting, validate_tree
from frr_proteus.render import render_bgp_instance

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "out"

Proto = FrrRouting.Routing.ControlPlaneProtocols.ControlPlaneProtocol
Bgp = Proto.Bgp
GlobalAfiSafi = Bgp.Global.AfiSafis.AfiSafi
NeighborAfiSafi = Bgp.Neighbors.Neighbor.AfiSafis.AfiSafi


def _new_bgp_instance(
    routing: FrrRouting, *, name: str, local_as: int, vrf: str = "default"
) -> Bgp:
    # frr-routing keys the control-plane-protocol list on (type, name, vrf)
    proto = Proto(type="frr-bgp:bgp", name=name, vrf=vrf)
    routing.routing.control_plane_protocols.control_plane_protocol.append(proto)
    proto.bgp.global_.local_as = local_as
    return proto.bgp


def _evpn_af(bgp: Bgp) -> GlobalAfiSafi.L2vpnEvpn:
    afi_safi = GlobalAfiSafi(afi_safi_name="l2vpn-evpn")
    bgp.global_.afi_safis.afi_safi.append(afi_safi)
    return afi_safi.l2vpn_evpn


def build_default_instance(routing: FrrRouting, *, local_as: int, router_id: str) -> Bgp:
    bgp = _new_bgp_instance(routing, name="default", local_as=local_as)
    bgp.global_.router_id = router_id

    neighbor = Bgp.Neighbors.Neighbor(remote_address="10.30.30.30")
    neighbor.neighbor_remote_as.remote_as_type = "internal"
    neighbor.afi_safis.afi_safi.append(
        NeighborAfiSafi(afi_safi_name="l2vpn-evpn", enabled=True)
    )
    bgp.neighbors.neighbor.append(neighbor)

    evpn = _evpn_af(bgp)
    evpn.advertise_all_vni = True
    evpn.advertise_svi_ip = True

    for vni_id, rd_ip in [(101, "10.10.10.10"), (102, "10.10.10.10")]:
        evpn.vni.append(
            GlobalAfiSafi.L2vpnEvpn.Vni(
                vni_id=vni_id,
                rd=f"{rd_ip}:{vni_id}",
                route_target_import=[f"65000:{vni_id}"],
                route_target_export=[f"65000:{vni_id}"],
            )
        )

    return bgp


def build_vrf_instance_auto_rt(routing: FrrRouting, *, local_as: int, vrf: str) -> Bgp:
    bgp = _new_bgp_instance(routing, name=vrf, local_as=local_as, vrf=vrf)

    evpn = _evpn_af(bgp)
    evpn.route_target_import.append("*:300")
    evpn.route_target_import.append("auto")

    return bgp


def build_vrf_instance_type5(routing: FrrRouting, *, local_as: int, vrf: str) -> Bgp:
    bgp = _new_bgp_instance(routing, name=vrf, local_as=local_as, vrf=vrf)

    evpn = _evpn_af(bgp)
    evpn.advertise_ipv4_unicast.enabled = True

    return bgp


def main() -> None:
    routing = FrrRouting()

    default = build_default_instance(routing, local_as=65000, router_id="10.10.10.10")
    vrf_red = build_vrf_instance_auto_rt(routing, local_as=65000, vrf="vrf-red")
    vrf_purple = build_vrf_instance_type5(routing, local_as=65000, vrf="vrf-purple")

    # Whole-tree pass: leafref integrity, mandatory leaves, list keys,
    # choice rules -- everything on-assignment validation cannot judge.
    validate_tree(routing)

    text = (
        render_bgp_instance(default)
        + render_bgp_instance(vrf_red, vrf="vrf-red")
        + render_bgp_instance(vrf_purple, vrf="vrf-purple")
    )

    OUT_DIR.mkdir(exist_ok=True)
    out_file = OUT_DIR / "evpn_frr.conf"
    out_file.write_text(text)
    print(f"--- {out_file} ---")
    print(text, end="")


if __name__ == "__main__":
    main()
