"""Step 1 prototype: build a two-router eBGP config as structured Python
data (via the pyangbind classes generated from FRR's own frr-bgp.yang) and
render it to bgpd config text.

Run with the generated bindings on the path, e.g.:
    PYTHONPATH=src python3 examples/basic_bgp.py
"""

import sys

sys.path.insert(0, "src")

from frr_proteus._generated.frr_bgp import frr_routing
from frr_proteus.render import render_bgp_instance


def build_bgp_instance(*, local_as: int, router_id: str, neighbor_addr: str, neighbor_remote_as_type: str, network: str):
    routing = frr_routing()
    proto = routing.routing.control_plane_protocols.control_plane_protocol.add(
        "frr-bgp:bgp bgp default"
    )
    bgp = proto.bgp

    bgp.global_.local_as = local_as
    bgp.global_.router_id = router_id

    neighbor = bgp.neighbors.neighbor.add(neighbor_addr)
    neighbor.neighbor_remote_as.remote_as_type = neighbor_remote_as_type

    afi_safi = bgp.global_.afi_safis.afi_safi.add("frr-rt:ipv4-unicast")
    afi_safi.ipv4_unicast.network_config.add(network)

    return bgp


def main() -> None:
    r1 = build_bgp_instance(
        local_as=65001,
        router_id="192.168.255.1",
        neighbor_addr="192.168.255.2",
        neighbor_remote_as_type="external",
        network="192.0.2.0/24",
    )
    r2 = build_bgp_instance(
        local_as=65002,
        router_id="192.168.255.2",
        neighbor_addr="192.168.255.1",
        neighbor_remote_as_type="external",
        network="198.51.100.0/24",
    )

    print(render_bgp_instance(r1), end="")
    print(render_bgp_instance(r2), end="")


if __name__ == "__main__":
    main()
