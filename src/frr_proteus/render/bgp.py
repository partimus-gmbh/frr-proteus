"""Render a pyangbind FRR-BGP YANG instance into bgpd CLI config text.

FRR's bgpd has no northbound backend: unlike staticd, ripd, and other
YANG-converted daemons, there is no bgpd/bgp_nb.c and no `cli_show`
callbacks to reuse (confirmed by `grep -rn cli_show frr/bgpd/` -- zero
hits). So there is no existing YANG-to-text mapping to derive
automatically; this module hand-replicates the relevant `vty_out` calls
from bgpd/bgp_vty.c (`bgp_config_write`, `bgp_config_write_family`, the
neighbor remote-as printing block) against the corresponding YANG paths.
Codegen (pyangbind) only gets us the typed, validated input structure --
not this rendering layer.
"""

from __future__ import annotations

# AFI-SAFI identityref name (frr-routing.yang, stripped of module prefix)
# -> the two CLI tokens bgp_vty.c's bgp_config_write_family() writes after
# "address-family". Only what step 1 needs; EVPN and friends get added
# once frr-proteus has a YANG model for them.
_AFI_SAFI_CLI_TEXT = {
    "ipv4-unicast": "ipv4 unicast",
    "ipv6-unicast": "ipv6 unicast",
}


def _strip_prefix(identityref: object) -> str:
    """"frr-rt:ipv4-unicast" -> "ipv4-unicast" (pyangbind identityrefs
    stringify with their defining module prefix)."""
    return str(identityref).split(":", 1)[-1]


def _remote_as_text(neighbor) -> str | None:
    """Mirror bgp_vty.c's peer->as_type switch (AS_SPECIFIED/INTERNAL/
    EXTERNAL/AUTO) for one neighbor's `remote-as` token."""
    ras = neighbor.neighbor_remote_as
    as_type_raw = ras.remote_as_type
    if not as_type_raw:
        return None
    as_type = _strip_prefix(as_type_raw)
    if as_type == "as-specified":
        return str(ras.remote_as)
    if as_type in ("internal", "external"):
        return as_type
    raise ValueError(f"unsupported remote-as-type {as_type!r}")


def _render_neighbors(bgp) -> list[str]:
    lines = []
    for addr, neighbor in bgp.neighbors.neighbor.items():
        remote_as = _remote_as_text(neighbor)
        if remote_as is not None:
            lines.append(f" neighbor {addr} remote-as {remote_as}")
    return lines


def _render_afi_safi(afi_safi) -> list[str]:
    name = _strip_prefix(afi_safi.afi_safi_name)
    cli_text = _AFI_SAFI_CLI_TEXT.get(name)
    if cli_text is None:
        raise ValueError(
            f"unsupported afi-safi {name!r}; only "
            f"{sorted(_AFI_SAFI_CLI_TEXT)} are implemented so far"
        )

    container = getattr(afi_safi, name.replace("-", "_"))
    body = [f"  network {prefix}" for prefix in container.network_config]
    if not body:
        return []

    return [f" address-family {cli_text}", *body, " exit-address-family"]


def render_bgp_instance(bgp, *, vrf: str | None = None) -> str:
    """Render one BGP YANG instance into bgpd config text.

    `bgp` is the pyangbind `bgp` container reachable at
    `.../control-plane-protocol/bgp` (i.e. `control_plane_protocol.bgp`,
    not the list entry itself). `vrf` is the name of the VRF this instance
    is bound to; leave it as None (or pass "default") for bgpd's default
    instance, which renders as a plain `router bgp <asn>` with no `vrf`
    clause, matching bgp_config_write() in bgpd/bgp_vty.c.
    """
    global_ = bgp.global_
    local_as = global_.local_as
    if not local_as:
        raise ValueError("bgp global/local-as is not set")

    header = f"router bgp {local_as}"
    if vrf and vrf != "default":
        header += f" vrf {vrf}"
    lines = [header]

    router_id = str(global_.router_id)
    if router_id:
        lines.append(f" bgp router-id {router_id}")

    lines.extend(_render_neighbors(bgp))

    for _, afi_safi in global_.afi_safis.afi_safi.items():
        lines.extend(_render_afi_safi(afi_safi))

    lines.append("!")
    return "\n".join(lines) + "\n"
