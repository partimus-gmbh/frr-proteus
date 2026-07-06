"""Tests for the experimental EVPN config scheme.

Three concerns, matching the architecture:
  1. The experimental-syntax renderers emit the scheme's own CLI.
  2. The STANDARD renderer is free of experimental knowledge -- given a
     tree with experimental fields set, it emits none of them.
  3. translate_experimental_to_standard converts an experimental config
     into a legacy proteus model (+ zebra VRF L3VNI mappings), warning
     via EvpnTranslationWarning on every lossy drop; the standard
     renderer then emits that legacy model.
Plus the validate_tree leafref/must checks on the experimental refs.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import (
    EvpnTranslationWarning,
    render_bgp_instance,
    render_experimental_bgp_instance,
    render_experimental_evpn_global,
    render_vrfs,
    translate_experimental_to_standard,
)

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


def _bgp(*instances) -> bindings.ProteusBgp:
    root = bindings.ProteusBgp()
    root.instance.extend(instances)
    return root


def _translate(bgp, evpn_global=None):
    """Translate, returning (result, [warning messages])."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", EvpnTranslationWarning)
        result = translate_experimental_to_standard(bgp, evpn_global)
    msgs = [
        str(w.message)
        for w in caught
        if issubclass(w.category, EvpnTranslationWarning)
    ]
    return result, msgs


# --------------------------------------------------------------------------
# 1. Experimental-syntax rendering (the scheme's own CLI, lossless)
# --------------------------------------------------------------------------


def test_experimental_instance_renders_native_syntax():
    instance = _new_instance(vrf="underlay-red")
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.vxlan_underlay = True
    evpn.auto_discover_vnis = True
    evpn.origination_l3vni.vni = 4001
    evpn.origination_l3vni.prefix_routes_only = True
    evi = _evi("blue-v100", underlay="underlay-red", l2vni=100)
    evi.route_target_both.as2.append(
        EvpnAf.VlanBasedEvi.RouteTargetBoth.As2(global_admin=65000, local_admin=100)
    )
    evpn.vlan_based_evi.append(evi)

    text = render_experimental_bgp_instance(instance)
    assert text.startswith("!\nrouter bgp 65000 vrf underlay-red\n")
    assert "  vxlan-underlay\n" in text
    assert "  auto-discover-vnis\n" in text
    assert "  origination-l3vni 4001 prefix-routes-only\n" in text
    assert "  vlan-based-evi blue-v100\n" in text
    assert "   underlay-vrf underlay-red\n" in text
    assert "   origination-l2vni 100\n" in text
    assert "   route-target both 65000:100\n" in text
    assert "  exit-evi\n" in text


def test_experimental_instance_removes_legacy_syntax():
    instance = _new_instance()
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.advertise_all_vni = True
    evpn.rd = "10.0.0.1:1"
    evpn.vni.append(EvpnAf.Vni(vni_id=101, rd="10.0.0.1:101"))
    evpn.auto_discover_vnis = True

    text = render_experimental_bgp_instance(instance)
    assert "  auto-discover-vnis\n" in text
    for legacy in ("advertise-all-vni", "  rd ", "vni 101"):
        assert legacy not in text, legacy


def test_experimental_evpn_global_renders():
    evpn = GlobalEvpn()
    evpn.default_underlay_vrf = "yellow"
    evi = _evi("shared-l2", underlay="underlay-red", l2vni=999)
    evi.route_target_import.as2.append(
        EvpnAf.VlanBasedEvi.RouteTargetImport.As2(global_admin=65000, local_admin=999)
    )
    evpn.vlan_based_evi.append(evi)

    text = render_experimental_evpn_global(evpn)
    assert text.startswith("!\nevpn\n")
    assert " default-underlay-vrf yellow\n" in text
    assert " vlan-based-evi shared-l2\n" in text
    assert "  origination-l2vni 999\n" in text
    assert "  route-target import 65000:999\n" in text
    assert text.endswith("exit\n")
    # unconfigured -> ""
    assert render_experimental_evpn_global(GlobalEvpn()) == ""


def test_neighbor_lines_render_in_both_paths():
    # Neighbor EVPN activation is shared vocabulary: present in the
    # experimental renderer and (after translation) the standard one.
    instance = _new_instance()
    instance.afi_safis.l2vpn_evpn.auto_discover_vnis = True
    n = Instance.Neighbor(address="10.30.30.30")
    n.remote_as.type = "internal"
    n.afi_safis.l2vpn_evpn.activate = True
    instance.neighbor.append(n)

    assert "  neighbor 10.30.30.30 activate\n" in render_experimental_bgp_instance(
        instance
    )
    result, _ = _translate(_bgp(instance))
    assert "  neighbor 10.30.30.30 activate\n" in render_bgp_instance(
        result.bgp.instance[0]
    )


def test_experimental_evi_blocks_are_separated_by_bang_lines():
    instance = _new_instance(vrf="underlay-red")
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.vxlan_underlay = True
    evpn.route_target_import.as2.append(
        EvpnAf.RouteTargetImport.As2(global_admin=65000, local_admin=1)
    )
    evpn.vlan_based_evi.append(_evi("evi-a", l2vni=100))
    evpn.vlan_based_evi.append(_evi("evi-b", l2vni=200))

    text = render_experimental_bgp_instance(instance)
    assert "  route-target import 65000:1\n  !\n  vlan-based-evi evi-a\n" in text
    assert "  exit-evi\n  !\n  vlan-based-evi evi-b\n" in text


# --------------------------------------------------------------------------
# 2. The standard renderer knows nothing about the experimental scheme
# --------------------------------------------------------------------------


def test_standard_renderer_ignores_experimental_fields():
    # An instance carrying BOTH legacy and experimental EVPN config: the
    # standard renderer emits the legacy config and NONE of the
    # experimental fields (no translation happens in the renderer).
    instance = _new_instance()
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.advertise_all_vni = True  # legacy -> rendered
    evpn.vni.append(EvpnAf.Vni(vni_id=101))  # legacy -> rendered
    # experimental fields -> must NOT appear, and must NOT be translated
    evpn.vxlan_underlay = True
    evpn.auto_discover_vnis = True
    evpn.underlay_vrf = "underlay-red"
    evpn.origination_l3vni.vni = 4001
    evpn.vlan_based_evi.append(_evi("v555", underlay="underlay-red", l2vni=555))

    text = render_bgp_instance(instance)
    assert "  advertise-all-vni\n" in text
    assert "  vni 101\n" in text
    for experimental in (
        "vxlan-underlay",
        "auto-discover-vnis",
        "underlay-vrf",
        "origination-l3vni",
        "vlan-based-evi",
        "vni 555",  # the EVI's L2VNI is NOT translated by the renderer
    ):
        assert experimental not in text, experimental


def test_standard_renderer_emits_no_warnings():
    instance = _new_instance()
    instance.afi_safis.l2vpn_evpn.vxlan_underlay = True
    instance.afi_safis.l2vpn_evpn.vlan_based_evi.append(_evi("v1", l2vni=1))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", EvpnTranslationWarning)
        render_bgp_instance(instance)
    assert not [
        w for w in caught if issubclass(w.category, EvpnTranslationWarning)
    ]


# --------------------------------------------------------------------------
# 3. The translator: experimental config -> standard (legacy) model
# --------------------------------------------------------------------------


def test_translate_vxlan_underlay_to_advertise_all_vni():
    instance = _new_instance(vrf="underlay-red")
    instance.afi_safis.l2vpn_evpn.vxlan_underlay = True
    result, msgs = _translate(_bgp(instance))

    evpn = result.bgp.instance[0].afi_safis.l2vpn_evpn
    assert evpn.advertise_all_vni is True
    assert evpn.vxlan_underlay is None  # experimental field cleared
    assert "  advertise-all-vni\n" in render_bgp_instance(result.bgp.instance[0])
    assert any("auto-discover" in m for m in msgs)

    # ...no auto-discover warning when auto-discover-vnis IS set
    instance.afi_safis.l2vpn_evpn.auto_discover_vnis = True
    _, msgs = _translate(_bgp(instance))
    assert not [m for m in msgs if "auto-discover" in m]


def test_translate_vlan_based_evi_to_legacy_vni():
    instance = _new_instance()
    evi = _evi("v100", l2vni=100)
    evi.route_target_both.as2.append(
        EvpnAf.VlanBasedEvi.RouteTargetBoth.As2(global_admin=65000, local_admin=100)
    )
    # wildcard/auto RTs have no home in a legacy vni block -> dropped
    evi.route_target_import.wildcard = [42]
    evi.route_target_import.auto = True
    evi.route_target_export.auto = True
    instance.afi_safis.l2vpn_evpn.vlan_based_evi.append(evi)

    result, msgs = _translate(_bgp(instance))
    evpn = result.bgp.instance[0].afi_safis.l2vpn_evpn
    assert not evpn.vlan_based_evi  # experimental list cleared
    (vni,) = evpn.vni
    assert vni.vni_id == 100
    assert vni.route_target_both.as2[0].global_admin == 65000

    text = render_bgp_instance(result.bgp.instance[0])
    assert "  vni 100\n" in text
    assert "   route-target both 65000:100\n" in text
    for dropped in ("*:42", "route-target import auto", "route-target export auto"):
        assert dropped not in text, dropped
    (msg,) = [m for m in msgs if "route-target option" in m]
    assert "import '*:NN' wildcard" in msg
    assert "import auto" in msg
    assert "export auto" in msg


def test_translate_evi_name_preserved_as_comment():
    # A legacy 'vni' block has no name field; the EVI name is kept as a
    # comment the standard renderer emits above the block.
    instance = _new_instance()
    instance.afi_safis.l2vpn_evpn.vlan_based_evi.append(_evi("tenant-blue", l2vni=100))
    result, _ = _translate(_bgp(instance))
    text = render_bgp_instance(result.bgp.instance[0])
    assert "  ! vlan-based-evi tenant-blue\n  vni 100\n" in text


def test_translate_evi_comment_merged_above_name():
    # An EVI the user already annotated keeps its own comment, with the
    # translated name comment below it (both '!' lines survive).
    instance = _new_instance()
    evi = _evi("tenant-blue", l2vni=100)
    bindings.annotate(evi, comment="prod tenant")
    instance.afi_safis.l2vpn_evpn.vlan_based_evi.append(evi)
    result, _ = _translate(_bgp(instance))
    text = render_bgp_instance(result.bgp.instance[0])
    assert (
        "  ! prod tenant\n  ! vlan-based-evi tenant-blue\n  vni 100\n" in text
    )


def test_translate_evi_without_l2vni_dropped():
    instance = _new_instance()
    instance.afi_safis.l2vpn_evpn.vlan_based_evi.append(_evi("no-vni"))
    result, msgs = _translate(_bgp(instance))
    assert not result.bgp.instance[0].afi_safis.l2vpn_evpn.vni
    assert any("dropped entirely" in m and "no-vni" in m for m in msgs)


def test_translate_origination_l3vni_tenant_to_vrf_block():
    instance = _new_instance(vrf="blue")
    instance.afi_safis.l2vpn_evpn.origination_l3vni.vni = 5001
    instance.afi_safis.l2vpn_evpn.origination_l3vni.prefix_routes_only = True
    result, _ = _translate(_bgp(instance))

    (vrf,) = result.vrfs.vrf
    assert (vrf.name, vrf.l3vni, vrf.prefix_routes_only) == ("blue", 5001, True)
    assert result.default_l3vni is None
    # origination-l3vni cleared off the instance
    assert result.bgp.instance[0].afi_safis.l2vpn_evpn.origination_l3vni.vni is None
    assert "vrf blue\n vni 5001 prefix-routes-only\nexit-vrf\n" in render_vrfs(
        result.vrfs, heading=None
    )


def test_translate_origination_l3vni_default_to_global_scalar():
    instance = _new_instance(vrf="default")
    instance.afi_safis.l2vpn_evpn.origination_l3vni.vni = 4000
    instance.afi_safis.l2vpn_evpn.origination_l3vni.prefix_routes_only = True
    result, _ = _translate(_bgp(instance))

    assert result.default_l3vni == 4000
    assert result.default_l3vni_prefix_routes_only is True
    assert not result.vrfs.vrf  # default VRF is NOT a vrf block
    text = render_vrfs(
        result.vrfs,
        heading=None,
        default_l3vni=result.default_l3vni,
        default_l3vni_prefix_routes_only=result.default_l3vni_prefix_routes_only,
    )
    assert text == "! default VRF L3VNI\nvni 4000 prefix-routes-only\n"


def test_translate_underlay_vrf_nondefault_warns():
    instance = _new_instance(vrf="blue")
    instance.afi_safis.l2vpn_evpn.underlay_vrf = "underlay-red"
    evi = _evi("v100", underlay="underlay-red", l2vni=100)
    instance.afi_safis.l2vpn_evpn.vlan_based_evi.append(evi)
    _, msgs = _translate(_bgp(instance))

    multi = [m for m in msgs if "multi-underlay" in m]
    assert len(multi) == 2  # instance-level + EVI-level
    assert any("vlan-based-evi 'v100'" in m for m in multi)

    # "default" underlay is representable -> no warning
    instance.afi_safis.l2vpn_evpn.underlay_vrf = "default"
    evi.underlay_vrf = "default"
    _, msgs = _translate(_bgp(instance))
    assert not [m for m in msgs if "multi-underlay" in m]


def test_translate_global_block_dropped_warns():
    evpn = GlobalEvpn()
    evpn.default_underlay_vrf = "underlay-red"
    evpn.vlan_based_evi.append(_evi("g100", underlay="underlay-red", l2vni=100))
    _, msgs = _translate(_bgp(), evpn)
    assert any("default-underlay-vrf underlay-red" in m for m in msgs)
    assert any("vlan-based-evi 'g100'" in m for m in msgs)


def test_translate_does_not_mutate_input():
    instance = _new_instance(vrf="underlay-red")
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.vxlan_underlay = True
    evpn.origination_l3vni.vni = 4000
    evpn.vlan_based_evi.append(_evi("v100", l2vni=100))
    bgp = _bgp(instance)

    _translate(bgp)  # discard result
    # original tree untouched: experimental fields still set, no legacy
    assert evpn.vxlan_underlay is True
    assert evpn.origination_l3vni.vni == 4000
    assert len(evpn.vlan_based_evi) == 1
    assert evpn.advertise_all_vni is None
    assert not evpn.vni


def test_translated_default_vrf_has_no_evpn_af_block():
    # A tenant whose only EVPN config is origination-l3vni translates to
    # a vrf block, leaving its router-bgp EVPN AF empty -> not emitted.
    instance = _new_instance(vrf="blue")
    instance.afi_safis.l2vpn_evpn.origination_l3vni.vni = 5001
    result, _ = _translate(_bgp(instance))
    assert "address-family l2vpn evpn" not in render_bgp_instance(
        result.bgp.instance[0]
    )


# --------------------------------------------------------------------------
# validate_tree: experimental leafref / must checks (unchanged)
# --------------------------------------------------------------------------


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
