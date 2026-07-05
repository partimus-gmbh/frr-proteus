"""Semantic validation the generated bindings cannot do themselves.

The generated ``validate_tree()`` checks leafref existence but never
evaluates YANG ``must`` expressions. The experimental EVPN scheme
(yang/custom/proteus-bgp-evpn-experimental.yang) states one such rule:
every ``underlay-vrf`` / ``default-underlay-vrf`` reference must point
at a BGP instance whose l2vpn-evpn address-family has
``vxlan-underlay`` set. This module enforces it in Python.
"""

from __future__ import annotations


def validate_underlay_refs(bgp_root, evpn_global_root=None) -> None:
    """Enforce the experimental scheme's vxlan-underlay 'must' rules.

    ``bgp_root`` is the generated ``ProteusBgp`` module root;
    ``evpn_global_root`` optionally the ``ProteusBgpEvpnExperimental``
    module root (for default-underlay-vrf and the global EVIs). Checks
    only the underlay *role*: that a referenced instance exists at all
    is the leafref's job -- run the bindings' ``validate_tree()``
    alongside this.

    Collects every violation and raises one ``ValueError`` listing
    them; returns None when clean.
    """
    instances = bgp_root.bgp.instance
    underlays = {
        instance.vrf
        for instance in instances
        if instance.afi_safis.l2vpn_evpn.vxlan_underlay
    }

    errors: list[str] = []

    def check(ref: str | None, where: str) -> None:
        if ref is not None and ref not in underlays:
            errors.append(
                f"{where}: references VRF {ref!r}, whose BGP instance is "
                "not marked vxlan-underlay"
            )

    for instance in instances:
        evpn = instance.afi_safis.l2vpn_evpn
        base = f"instance[vrf={instance.vrf!r}]/afi-safis/l2vpn-evpn"
        check(evpn.underlay_vrf, f"{base}/underlay-vrf")
        for evi in evpn.vlan_based_evi:
            check(
                evi.underlay_vrf,
                f"{base}/vlan-based-evi[name={evi.name!r}]/underlay-vrf",
            )

    if evpn_global_root is not None:
        evpn = evpn_global_root.evpn
        check(evpn.default_underlay_vrf, "evpn/default-underlay-vrf")
        for evi in evpn.vlan_based_evi:
            check(
                evi.underlay_vrf,
                f"evpn/vlan-based-evi[name={evi.name!r}]/underlay-vrf",
            )

    if errors:
        raise ValueError(
            "%d underlay reference violation(s):\n  %s"
            % (len(errors), "\n  ".join(errors))
        )
