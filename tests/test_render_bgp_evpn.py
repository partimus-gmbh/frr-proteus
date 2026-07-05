from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from frr_proteus.render import render_bgp_instance

# Import statically for type checkers so the deeply-nested binding classes keep
# their real types; at runtime use importorskip so the suite skips cleanly when
# bindings haven't been generated. Both paths bind `bindings` to the same module.
if TYPE_CHECKING:
    from frr_proteus._generated import proteus as bindings
else:
    bindings = pytest.importorskip("frr_proteus._generated.proteus")

# These bindings double as annotations *and* are instantiated below.
# `TypeAlias` marks them as aliases while keeping normal assignments, so the
# values stay callable. A PEP 695 `type X = ...` can't be used here: a
# TypeAliasType is neither callable nor attribute-accessible.
Instance: TypeAlias = bindings.ProteusBgp.Bgp.Instance
EvpnAf: TypeAlias = Instance.AfiSafis.L2vpnEvpn


def _new_instance(vrf: str = "default") -> Instance:
    return Instance(vrf=vrf, autonomous_system=65000)


def _add_neighbor(instance: Instance, addr: str) -> Instance.Neighbor:
    neighbor = Instance.Neighbor(address=addr)
    instance.neighbor.append(neighbor)
    return neighbor


def test_advertise_all_vni():
    instance = _new_instance()
    instance.afi_safis.l2vpn_evpn.advertise_all_vni = True

    text = render_bgp_instance(instance)
    assert " address-family l2vpn evpn\n" in text
    assert "  advertise-all-vni\n" in text
    assert " exit-address-family\n" in text


def test_advertise_default_gw_and_svi_ip_and_resolve_overlay():
    instance = _new_instance()
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.advertise_default_gw = True
    evpn.advertise_svi_ip = True
    evpn.enable_resolve_overlay_index = True

    text = render_bgp_instance(instance)
    assert "  advertise-default-gw\n" in text
    assert "  advertise-svi-ip\n" in text
    assert "  enable-resolve-overlay-index\n" in text


@pytest.mark.parametrize("value", ["disable", "head-end-replication"])
def test_flooding(value):
    instance = _new_instance()
    instance.afi_safis.l2vpn_evpn.flooding = value

    assert f"  flooding {value}\n" in render_bgp_instance(instance)


def test_vni_block():
    instance = _new_instance()
    vni = EvpnAf.Vni(vni_id=101, rd="10.10.10.10:101", flooding="disable")
    vni.route_target_import.as2.append(
        EvpnAf.Vni.RouteTargetImport.As2(global_admin=65000, local_admin=101)
    )
    vni.route_target_export.as2.append(
        EvpnAf.Vni.RouteTargetExport.As2(global_admin=65000, local_admin=101)
    )
    vni.route_target_both.as2.append(
        EvpnAf.Vni.RouteTargetBoth.As2(global_admin=65000, local_admin=999)
    )
    instance.afi_safis.l2vpn_evpn.vni.append(vni)

    text = render_bgp_instance(instance)
    assert "  vni 101\n" in text
    assert "   rd 10.10.10.10:101\n" in text
    assert "   route-target import 65000:101\n" in text
    assert "   route-target export 65000:101\n" in text
    assert "   route-target both 65000:999\n" in text
    assert "   flooding disable\n" in text
    assert "  exit-vni\n" in text


def test_vrf_rd_and_route_target():
    instance = _new_instance(vrf="vrf-red")
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.rd = "10.10.10.10:101"
    evpn.route_target_import.as2.append(
        EvpnAf.RouteTargetImport.As2(global_admin=65000, local_admin=300)
    )

    text = render_bgp_instance(instance)
    assert "  rd 10.10.10.10:101\n" in text
    assert "  route-target import 65000:300\n" in text


def test_vrf_route_target_wildcard_and_auto():
    instance = _new_instance(vrf="vrf-red")
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.route_target_import.wildcard = [300]
    evpn.route_target_import.auto = True
    evpn.route_target_export.auto = True

    text = render_bgp_instance(instance)
    assert "  route-target import *:300\n" in text
    assert "  route-target import auto\n" in text
    assert "  route-target export auto\n" in text


def test_vrf_route_target_export_all_encodings():
    instance = _new_instance(vrf="vrf-red")
    export = instance.afi_safis.l2vpn_evpn.route_target_export
    export.as2.append(
        EvpnAf.RouteTargetExport.As2(global_admin=65000, local_admin=4200000000)
    )
    export.as4.append(
        EvpnAf.RouteTargetExport.As4(global_admin=4200000000, local_admin=100)
    )
    export.ipv4.append(
        EvpnAf.RouteTargetExport.Ipv4(global_admin="10.10.10.10", local_admin=100)
    )

    text = render_bgp_instance(instance)
    assert "  route-target export 65000:4200000000\n" in text
    assert "  route-target export 4200000000:100\n" in text
    assert "  route-target export 10.10.10.10:100\n" in text


def test_route_target_wildcard_and_auto_are_import_only():
    # export has no wildcard field, VNI RT sets have neither wildcard
    # nor auto -- the invalid combinations are structurally impossible,
    # not just invalid values.
    import dataclasses

    export_fields = {
        f.name for f in dataclasses.fields(EvpnAf.RouteTargetExport)
    }
    assert "wildcard" not in export_fields
    assert "auto" in export_fields

    both_fields = {f.name for f in dataclasses.fields(EvpnAf.RouteTargetBoth)}
    assert "wildcard" not in both_fields
    assert "auto" not in both_fields

    for cls in (
        EvpnAf.Vni.RouteTargetImport,
        EvpnAf.Vni.RouteTargetExport,
        EvpnAf.Vni.RouteTargetBoth,
    ):
        names = {f.name for f in dataclasses.fields(cls)}
        assert "wildcard" not in names
        assert "auto" not in names


def test_route_target_component_ranges_enforced():
    # as2: 2-byte AS, 4-byte local admin; as4: the reverse.
    with pytest.raises(bindings.YangValidationError):
        EvpnAf.RouteTargetExport.As2(global_admin=70000, local_admin=100)
    with pytest.raises(bindings.YangValidationError):
        EvpnAf.RouteTargetExport.As4(global_admin=65000, local_admin=70000)
    with pytest.raises(bindings.YangValidationError):
        EvpnAf.RouteTargetExport.As2(global_admin=65000, local_admin=4294967296)
    with pytest.raises(bindings.YangValidationError):
        EvpnAf.RouteTargetExport.Ipv4(global_admin="999.1.1.1", local_admin=100)
    with pytest.raises(bindings.YangValidationError):
        instance = _new_instance(vrf="vrf-red")
        instance.afi_safis.l2vpn_evpn.route_target_import.wildcard = [4294967296]


@pytest.mark.parametrize(
    "gateway_ip,route_map,expected",
    [
        (False, None, "advertise ipv4 unicast\n"),
        (True, None, "advertise ipv4 unicast gateway-ip\n"),
        (False, "RMAP4", "advertise ipv4 unicast route-map RMAP4\n"),
        (True, "RMAP4", "advertise ipv4 unicast gateway-ip route-map RMAP4\n"),
    ],
)
def test_advertise_ipv4_unicast(gateway_ip, route_map, expected):
    instance = _new_instance(vrf="vrf-purple")
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.advertise_ipv4_unicast.enabled = True
    evpn.advertise_ipv4_unicast.gateway_ip = gateway_ip
    if route_map:
        evpn.advertise_ipv4_unicast.route_map = route_map

    assert f"  {expected}" in render_bgp_instance(instance)


def test_advertise_ipv6_unicast():
    instance = _new_instance(vrf="vrf-purple")
    instance.afi_safis.l2vpn_evpn.advertise_ipv6_unicast.enabled = True

    assert "  advertise ipv6 unicast\n" in render_bgp_instance(instance)


def test_neighbor_evpn_activate():
    instance = _new_instance()
    n = _add_neighbor(instance, "192.0.2.1")
    n.remote_as = "internal"
    n.afi_safis.l2vpn_evpn.activate = True

    assert "  neighbor 192.0.2.1 activate\n" in render_bgp_instance(instance)


def test_neighbor_evpn_route_reflector_client():
    instance = _new_instance()
    n = _add_neighbor(instance, "192.0.2.1")
    n.afi_safis.l2vpn_evpn.route_reflector_client = True

    assert "  neighbor 192.0.2.1 route-reflector-client\n" in render_bgp_instance(
        instance
    )


def test_neighbor_evpn_route_map_in_and_out():
    instance = _new_instance()
    n = _add_neighbor(instance, "192.0.2.1")
    n.afi_safis.l2vpn_evpn.filters.route_map_in = "RM-IN"
    n.afi_safis.l2vpn_evpn.filters.route_map_out = "RM-OUT"

    text = render_bgp_instance(instance)
    assert "  neighbor 192.0.2.1 route-map RM-IN in\n" in text
    assert "  neighbor 192.0.2.1 route-map RM-OUT out\n" in text


def test_neighbor_evpn_allowas_in():
    instance = _new_instance()
    n = _add_neighbor(instance, "192.0.2.1")
    n.afi_safis.l2vpn_evpn.allowas_in.enabled = True
    n.afi_safis.l2vpn_evpn.allowas_in.count = 2

    assert "  neighbor 192.0.2.1 allowas-in 2\n" in render_bgp_instance(instance)


def test_neighbor_evpn_allowas_in_bare():
    # Bare 'allowas-in' (FRR's default count of 3) when only enabled is set.
    instance = _new_instance()
    n = _add_neighbor(instance, "192.0.2.1")
    n.afi_safis.l2vpn_evpn.allowas_in.enabled = True

    assert "  neighbor 192.0.2.1 allowas-in\n" in render_bgp_instance(instance)


def test_evpn_af_omitted_without_evpn_config():
    instance = _new_instance()
    n = _add_neighbor(instance, "192.0.2.1")
    n.remote_as = "internal"
    # No EVPN config anywhere -- the AF block itself must not appear.
    assert "address-family l2vpn evpn" not in render_bgp_instance(instance)
