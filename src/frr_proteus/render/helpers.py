"""Small pyangbind-to-Jinja glue functions for the bgp.conf.j2 template.

Kept deliberately thin: anything that's just "read this YANG field and
print it" belongs in the template. What lives here is logic the template
can't reasonably express -- picking apart an enum-typed leaf
(remote-as-type), or FRR's `identityref` string values (which the
underlying libyang/pyangbind stack always renders module-prefixed, e.g.
"frr-rt:ipv4-unicast").
"""

from __future__ import annotations

# AFI-SAFI identityref name (stripped of module prefix) -> the two CLI
# tokens bgp_vty.c's bgp_config_write_family() writes after
# "address-family". Only what step 1 needs; EVPN and others get added
# once frr-proteus has a YANG model for them.
_AFI_SAFI_CLI_TEXT = {
    "ipv4-unicast": "ipv4 unicast",
    "ipv6-unicast": "ipv6 unicast",
    "l2vpn-evpn": "l2vpn evpn",
}


def strip_yang_prefix(identityref: object) -> str:
    """"frr-rt:ipv4-unicast" -> "ipv4-unicast"."""
    return str(identityref).split(":", 1)[-1]


def afi_safi_name(afi_safi) -> str:
    return strip_yang_prefix(afi_safi.afi_safi_name)


def afi_safi_cli_text(afi_safi) -> str:
    name = afi_safi_name(afi_safi)
    cli_text = _AFI_SAFI_CLI_TEXT.get(name)
    if cli_text is None:
        raise ValueError(
            f"unsupported afi-safi {name!r}; only "
            f"{sorted(_AFI_SAFI_CLI_TEXT)} are implemented so far"
        )
    return cli_text


def afi_safi_networks(afi_safi) -> list[str]:
    """Prefixes configured under this afi-safi's `network-config` list,
    e.g. from `bgp.global_.afi_safis.afi_safi["frr-rt:ipv4-unicast"]`."""
    container = getattr(afi_safi, afi_safi_name(afi_safi).replace("-", "_"))
    return list(container.network_config)


def neighbor_afi_safi(neighbor, name: str):
    """`neighbor`'s afi-safi list entry named `name` (e.g. "l2vpn-evpn",
    with or without the "frr-rt:" prefix), or None if this neighbor has
    no configuration for that AFI-SAFI at all. pyangbind's dict-like
    `.get()` returns an empty OrderedDict rather than None on a miss (not
    something a template can easily branch on), so this normalizes that
    to a plain `in` check."""
    key = name if ":" in name else f"frr-rt:{name}"
    if key not in neighbor.afi_safis.afi_safi:
        return None
    return neighbor.afi_safis.afi_safi[key]


def remote_as_text(neighbor) -> str | None:
    """Mirror bgp_vty.c's peer->as_type switch (AS_SPECIFIED/INTERNAL/
    EXTERNAL/AUTO) for one neighbor's `remote-as` token."""
    ras = neighbor.neighbor_remote_as
    as_type_raw = ras.remote_as_type
    if not as_type_raw:
        return None
    as_type = strip_yang_prefix(as_type_raw)
    if as_type == "as-specified":
        return str(ras.remote_as)
    if as_type in ("internal", "external"):
        return as_type
    raise ValueError(f"unsupported remote-as-type {as_type!r}")
