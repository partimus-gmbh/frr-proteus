"""Step 1 prototype: build a two-router eBGP config as structured Python
data (via the typed dataclasses generated from the custom
yang/custom/proteus-bgp.yang model) and render it to bgpd config text.

Writes rendered bgpd config text to out/r1_bgpd.conf and out/r2_bgpd.conf
(relative to the repo root) for evaluation. Run with the generated
bindings on the path, e.g.:
    PYTHONPATH=src python3 examples/basic_bgp.py
"""

import pathlib
import sys
from typing import TypeAlias

sys.path.insert(0, "src")

from frr_proteus._generated.proteus import ProteusBgp, validate_tree
from frr_proteus.render import render_bgp_instance

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "out"

Instance: TypeAlias = ProteusBgp.Bgp.Instance


def build_router(
    *,
    local_as: int,
    router_id: str,
    neighbor_addr: str,
    neighbor_remote_as: int | str,
    network: str,
) -> ProteusBgp:
    root = ProteusBgp()
    instance = Instance(
        vrf="default", autonomous_system=local_as, router_id=router_id
    )
    instance.neighbor.append(
        Instance.Neighbor(address=neighbor_addr, remote_as=neighbor_remote_as)
    )
    instance.afi_safis.ipv4_unicast.network.append(
        Instance.AfiSafis.Ipv4Unicast.Network(prefix=network)
    )
    root.bgp.instance.append(instance)
    return root


def main() -> None:
    r1 = build_router(
        local_as=65001,
        router_id="192.168.255.1",
        neighbor_addr="192.168.255.2",
        neighbor_remote_as="external",
        network="192.0.2.0/24",
    )
    r2 = build_router(
        local_as=65002,
        router_id="192.168.255.2",
        neighbor_addr="192.168.255.1",
        neighbor_remote_as="external",
        network="198.51.100.0/24",
    )

    OUT_DIR.mkdir(exist_ok=True)
    for name, root in [("r1_bgpd.conf", r1), ("r2_bgpd.conf", r2)]:
        # Whole-tree pass: mandatory leaves, list keys, leafrefs --
        # everything on-assignment validation cannot judge.
        validate_tree(root)
        text = "".join(
            render_bgp_instance(instance) for instance in root.bgp.instance
        )
        (OUT_DIR / name).write_text(text)
        print(f"--- {OUT_DIR / name} ---")
        print(text, end="")


if __name__ == "__main__":
    main()
