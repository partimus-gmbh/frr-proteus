"""Tests for the experimental EVPN config scheme: its own output format
(new syntax, legacy syntax removed) and the frr-format compatibility
translation (new typing rendered as stock FRR syntax where an
equivalent exists, left out where none does)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_bgp_instance, render_evpn_global

if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

Instance: TypeAlias = bindings.ProteusBgp.Instance
EvpnAf: TypeAlias = Instance.AfiSafis.L2vpnEvpn
GlobalEvpn: TypeAlias = bindings.ProteusBgpEvpnExperimental.Evpn


def _new_instance(vrf: str = "default", asn: int = 65000) -> Instance:
    instance = Instance(vrf=vrf)
    instance.autonomous_system.plain = asn
    return instance


def _evi(name: str, *, underlay: str | None = None, l2vni: int | None = None):
    evi = EvpnAf.VlanBasedEvi(name=name)
    if underlay:
        evi.underlay_vrf = underlay
    if l2vni:
        evi.origination_l2vni = l2vni
    return evi


def test_underlay_instance_experimental_format():
    instance = _new_instance(vrf="underlay-red")
    instance.afi_safis.l2vpn_evpn.vxlan_underlay = True
    instance.afi_safis.l2vpn_evpn.auto_discover_vnis = True

    text = render_bgp_instance(instance, format="experimental")
    assert text.startswith("router bgp 65000 vrf underlay-red\n")
    assert " address-family l2vpn evpn\n" in text
    assert "  vxlan-underlay\n" in text
    assert "  auto-discover-vnis\n" in text
    assert " exit-address-family\n" in text


def test_tenant_instance_experimental_format():
    instance = _new_instance(vrf="blue")
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.underlay_vrf = "underlay-red"
    evpn.origination_l3vni.vni = 4001
    evpn.origination_l3vni.prefix_routes_only = True
    evpn.route_target_import.auto = True
    evpn.route_target_export.auto = True
    evpn.route_target_import.wildcard = [111]

    evi = _evi("blue-v100", underlay="underlay-red", l2vni=100)
    evi.route_target_both.as2.append(
        EvpnAf.VlanBasedEvi.RouteTargetBoth.As2(global_admin=65000, local_admin=100)
    )
    evpn.vlan_based_evi.append(evi)

    text = render_bgp_instance(instance, format="experimental")
    assert "  underlay-vrf underlay-red\n" in text
    assert "  origination-l3vni 4001 prefix-routes-only\n" in text
    assert "  route-target import *:111\n" in text
    assert "  route-target import auto\n" in text
    assert "  route-target export auto\n" in text
    assert "  vlan-based-evi blue-v100\n" in text
    assert "   underlay-vrf underlay-red\n" in text
    assert "   origination-l2vni 100\n" in text
    assert "   route-target both 65000:100\n" in text
    assert "  exit-evi\n" in text


def test_origination_l3vni_without_prefix_routes_only():
    instance = _new_instance(vrf="blue")
    instance.afi_safis.l2vpn_evpn.origination_l3vni.vni = 4001

    text = render_bgp_instance(instance, format="experimental")
    assert "  origination-l3vni 4001\n" in text
    assert "prefix-routes-only" not in text


def test_experimental_format_removes_legacy_syntax():
    instance = _new_instance()
    evpn = instance.afi_safis.l2vpn_evpn
    # legacy fields...
    evpn.advertise_all_vni = True
    evpn.advertise_svi_ip = True
    evpn.flooding = "disable"
    evpn.rd = "10.0.0.1:1"
    evpn.advertise_ipv4_unicast.enabled = True
    evpn.vni.append(EvpnAf.Vni(vni_id=101, rd="10.0.0.1:101"))
    # ...and one experimental field
    evpn.auto_discover_vnis = True

    text = render_bgp_instance(instance, format="experimental")
    assert "  auto-discover-vnis\n" in text
    for legacy in (
        "advertise-all-vni",
        "advertise-svi-ip",
        "flooding",
        "  rd ",
        "advertise ipv4 unicast",
        "vni 101",
    ):
        assert legacy not in text, legacy


def test_neighbor_lines_render_in_both_formats():
    instance = _new_instance()
    instance.afi_safis.l2vpn_evpn.auto_discover_vnis = True
    n = Instance.Neighbor(address="10.30.30.30")
    n.remote_as.type = "internal"
    n.afi_safis.l2vpn_evpn.activate = True
    instance.neighbor.append(n)

    for format in ("frr", "experimental"):
        text = render_bgp_instance(instance, format=format)
        assert "  neighbor 10.30.30.30 activate\n" in text, format


def test_frr_format_translates_evi_to_vni_block():
    instance = _new_instance()
    evi = _evi("blue-v100", underlay="underlay-red", l2vni=100)
    evi.route_target_both.as2.append(
        EvpnAf.VlanBasedEvi.RouteTargetBoth.As2(global_admin=65000, local_admin=100)
    )
    # wildcard and auto exist on the EVI but stock 'vni' RT lines can't
    # express them -- the translation must drop them.
    evi.route_target_import.wildcard = [42]
    evi.route_target_import.auto = True
    instance.afi_safis.l2vpn_evpn.vlan_based_evi.append(evi)

    text = render_bgp_instance(instance, format="frr")
    assert "  vni 100\n" in text
    assert "   route-target both 65000:100\n" in text
    assert "  exit-vni\n" in text
    for dropped in ("vlan-based-evi", "underlay-vrf", "*:42", "auto"):
        assert dropped not in text, dropped


def test_frr_format_drops_evi_without_l2vni_and_underlay_fields():
    instance = _new_instance(vrf="blue")
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.vxlan_underlay = True
    evpn.auto_discover_vnis = True
    evpn.underlay_vrf = "underlay-red"
    evpn.origination_l3vni.vni = 4001
    evpn.vlan_based_evi.append(_evi("no-vni", underlay="underlay-red"))
    # something legacy so the AF block renders at all
    evpn.advertise_all_vni = True

    text = render_bgp_instance(instance, format="frr")
    assert "  advertise-all-vni\n" in text
    for dropped in (
        "vxlan-underlay",
        "auto-discover-vnis",
        "underlay-vrf",
        "origination-l3vni",
        "vlan-based-evi",
        "no-vni",
    ):
        assert dropped not in text, dropped


def test_frr_format_omits_af_block_for_untranslatable_only_config():
    # Only untranslatable experimental fields: the frr format must not
    # emit an empty AF block.
    instance = _new_instance(vrf="underlay-red")
    instance.afi_safis.l2vpn_evpn.auto_discover_vnis = True

    assert "address-family l2vpn evpn" not in render_bgp_instance(
        instance, format="frr"
    )
    # ...but a translatable EVI alone does warrant the block.
    instance.afi_safis.l2vpn_evpn.vlan_based_evi.append(
        _evi("v100", l2vni=100)
    )
    text = render_bgp_instance(instance, format="frr")
    assert " address-family l2vpn evpn\n" in text
    assert "  vni 100\n" in text


def test_frr_format_translates_vxlan_underlay_to_advertise_all_vni():
    instance = _new_instance(vrf="underlay-red")
    instance.afi_safis.l2vpn_evpn.vxlan_underlay = True

    text = render_bgp_instance(instance, format="frr")
    assert "  advertise-all-vni\n" in text
    assert "vxlan-underlay" not in text

    # both fields set: still exactly one advertise-all-vni line
    instance.afi_safis.l2vpn_evpn.advertise_all_vni = True
    assert render_bgp_instance(instance, format="frr").count(
        "advertise-all-vni"
    ) == 1

    # and the experimental format keeps the native spelling only
    exp = render_bgp_instance(instance, format="experimental")
    assert "  vxlan-underlay\n" in exp
    assert "advertise-all-vni" not in exp


def test_legacy_and_experimental_coexist_in_experimental_format():
    # both typings on one object: experimental format keeps the new
    # scheme and the shared RT syntax, frr format keeps legacy + the
    # translatable subset.
    instance = _new_instance()
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.advertise_all_vni = True
    evpn.auto_discover_vnis = True
    evpn.route_target_import.as2.append(
        EvpnAf.RouteTargetImport.As2(global_admin=65000, local_admin=1)
    )

    exp = render_bgp_instance(instance, format="experimental")
    frr = render_bgp_instance(instance, format="frr")
    assert "  route-target import 65000:1\n" in exp
    assert "  route-target import 65000:1\n" in frr
    assert "auto-discover-vnis" in exp and "auto-discover-vnis" not in frr
    assert "advertise-all-vni" in frr and "advertise-all-vni" not in exp


def test_render_evpn_global_experimental():
    evpn = GlobalEvpn()
    evpn.default_underlay_vrf = "yellow"
    evi = _evi("shared-l2", underlay="underlay-red", l2vni=999)
    evi.route_target_import.as2.append(
        EvpnAf.VlanBasedEvi.RouteTargetImport.As2(global_admin=65000, local_admin=999)
    )
    evpn.vlan_based_evi.append(evi)

    text = render_evpn_global(evpn, format="experimental")
    assert text.startswith("evpn\n")
    assert " default-underlay-vrf yellow\n" in text
    assert " vlan-based-evi shared-l2\n" in text
    assert "  underlay-vrf underlay-red\n" in text
    assert "  origination-l2vni 999\n" in text
    assert "  route-target import 65000:999\n" in text
    assert " exit-evi\n" in text
    assert text.endswith("exit\n!\n")


def test_render_evpn_global_frr_format_is_empty():
    evpn = GlobalEvpn()
    evpn.default_underlay_vrf = "yellow"
    # no stock-FRR equivalent exists: the compatibility rule is to
    # leave it out entirely.
    assert render_evpn_global(evpn, format="frr") == ""
    assert render_evpn_global(GlobalEvpn(), format="experimental") == ""


def test_unknown_format_rejected():
    with pytest.raises(ValueError, match="unknown output format"):
        render_bgp_instance(_new_instance(), format="fancy")
    with pytest.raises(ValueError, match="unknown output format"):
        render_evpn_global(GlobalEvpn(), format="fancy")


def test_underlay_vrf_leafref_enforced():
    root = bindings.ProteusBgp()
    exp_root = bindings.ProteusBgpEvpnExperimental()
    underlay = _new_instance(vrf="underlay-red")
    underlay.afi_safis.l2vpn_evpn.vxlan_underlay = True
    tenant = _new_instance(vrf="blue")
    tenant.afi_safis.l2vpn_evpn.underlay_vrf = "underlay-red"
    root.instance.extend([underlay, tenant])
    exp_root.evpn.default_underlay_vrf = "underlay-red"
    bindings.validate_tree(root, exp_root)

    tenant.afi_safis.l2vpn_evpn.underlay_vrf = "missing-vrf"
    with pytest.raises(bindings.YangValidationError, match="leafref"):
        bindings.validate_tree(root, exp_root)


def test_underlay_vrf_must_enforces_vxlan_underlay_role():
    root = bindings.ProteusBgp()
    exp_root = bindings.ProteusBgpEvpnExperimental()
    underlay = _new_instance(vrf="underlay-red")
    underlay.afi_safis.l2vpn_evpn.vxlan_underlay = True
    tenant = _new_instance(vrf="blue")
    tenant.afi_safis.l2vpn_evpn.underlay_vrf = "underlay-red"
    evi = _evi("blue-v100", underlay="underlay-red", l2vni=100)
    tenant.afi_safis.l2vpn_evpn.vlan_based_evi.append(evi)
    root.instance.extend([underlay, tenant])
    exp_root.evpn.default_underlay_vrf = "underlay-red"
    exp_root.evpn.vlan_based_evi.append(_evi("shared", underlay="underlay-red"))

    bindings.validate_tree(root, exp_root)  # all point at a marked VRF

    # the referenced instance exists (leafref fine!) but lacks the
    # vxlan-underlay role -- exactly the case the leafref can't catch
    # and the YANG `must` statements do: validate_tree evaluates them
    underlay.afi_safis.l2vpn_evpn.vxlan_underlay = False
    with pytest.raises(
        bindings.YangValidationError, match="must reference a VRF"
    ) as exc:
        bindings.validate_tree(root, exp_root)
    # every reference site is reported: tenant, tenant EVI, global
    # default, global EVI
    assert "4 violation(s)" in str(exc.value)