"""Smallest possible frr-proteus example: one BGP instance, one
neighbor, printed to stdout.

    PYTHONPATH=src python3 examples/minimal_bgp.py
"""

import ipaddress

from frr_proteus._generated.proteus import ProteusBgp, validate_tree
from frr_proteus.render import render_bgp_instance

# Top-Level YANG modules
pr_bgp = ProteusBgp()

# Create a single BGP instance with some basic properties
instance = ProteusBgp.Instance(vrf="default", router_id="192.0.2.1")
instance.autonomous_system.plain = 65000

# Add a neighbor to the instance with a simple remote AS
neighbor = ProteusBgp.Instance.Neighbor(
    address=ipaddress.IPv4Address("192.0.2.2")
)
neighbor.remote_as.plain = 65001
instance.neighbor.append(neighbor)

instance.afi_safis.ipv4_unicast.network.append(
    ProteusBgp.Instance.AfiSafis.Ipv4Unicast.Network(
        prefix=ipaddress.IPv4Network("198.51.100.0/24")
    )
)

pr_bgp.instance.append(instance)

validate_tree(pr_bgp)
print(render_bgp_instance(instance), end="")
