from __future__ import annotations

import ipaddress

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
Instance: TypeAlias = bindings.ProteusBgp.Instance
EvpnAf: TypeAlias = Instance.AfiSafis.L2vpnEvpn


def _new_instance(vrf: str = "default") -> Instance:
    instance = Instance(vrf=vrf)
    instance.autonomous_system.plain = 65000
    return instance


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
    vni = EvpnAf.Vni(vni_id=101, flooding="disable")
    vni.rd.ipv4.administrator = ipaddress.ip_address("10.10.10.10")
    vni.rd.ipv4.assigned_number = 101
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
    evpn.rd.ipv4.administrator = ipaddress.ip_address("10.10.10.10")
    evpn.rd.ipv4.assigned_number = 101
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
        EvpnAf.RouteTargetExport.Ipv4(
            global_admin=ipaddress.ip_address("10.10.10.10"), local_admin=100
        )
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
    n.remote_as.type = "internal"
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
    n.remote_as.type = "internal"
    # No EVPN config anywhere -- the AF block itself must not appear.
    assert "address-family l2vpn evpn" not in render_bgp_instance(instance)


# --- instance-side nodes added with the parity pass
#     (bgp_config_write_evpn_info in bgpd/bgp_evpn_vty.c) ---


def test_autort_and_mac_vrf_soo():
    instance = _new_instance()
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.autort_rfc8365_compatible = True
    evpn.mac_vrf_soo.ipv4.global_admin = ipaddress.ip_address("192.0.2.10")
    evpn.mac_vrf_soo.ipv4.local_admin = 100
    text = render_bgp_instance(instance)
    assert "  autort rfc8365-compatible\n" in text
    assert "  mac-vrf soo 192.0.2.10:100\n" in text


def test_multihoming_knobs():
    instance = _new_instance()
    mh = instance.afi_safis.l2vpn_evpn.multihoming
    mh.ead_es_frag_evi_limit = 200
    mh.use_es_l3nhg = False
    mh.disable_ead_evi_rx = True
    mh.disable_ead_evi_tx = False
    text = render_bgp_instance(instance)
    assert "  ead-es-frag evi-limit 200\n" in text
    assert "  no use-es-l3nhg\n" in text
    assert "  disable-ead-evi-rx\n" in text
    assert "  no disable-ead-evi-tx\n" in text


def test_ead_es_route_target_export():
    instance = _new_instance()
    mh = instance.afi_safis.l2vpn_evpn.multihoming
    As2 = type(mh.ead_es_route_target_export).As2
    mh.ead_es_route_target_export.as2.append(
        As2(global_admin=65000, local_admin=9999)
    )
    text = render_bgp_instance(instance)
    assert "  ead-es-route-target export 65000:9999\n" in text


def test_dup_addr_detection():
    instance = _new_instance()
    dad = instance.afi_safis.l2vpn_evpn.dup_addr_detection
    dad.enabled = False
    text = render_bgp_instance(instance)
    assert "  no dup-addr-detection\n" in text
    dad.enabled = None
    dad.max_moves = 10
    dad.time = 600
    text = render_bgp_instance(instance)
    assert "  dup-addr-detection max-moves 10 time 600\n" in text
    dad.freeze = "permanent"
    assert "  dup-addr-detection freeze permanent\n" in (
        render_bgp_instance(instance)
    )
    dad.freeze = 300
    assert "  dup-addr-detection freeze 300\n" in render_bgp_instance(instance)


def test_default_originate_and_advertise_pip():
    instance = _new_instance(vrf="TEN1")
    evpn = instance.afi_safis.l2vpn_evpn
    evpn.default_originate.ipv4 = True
    evpn.default_originate.ipv6 = True
    evpn.advertise_pip.enabled = False
    text = render_bgp_instance(instance)
    assert "  default-originate ipv4\n" in text
    assert "  default-originate ipv6\n" in text
    assert "  no advertise-pip\n" in text
    evpn.advertise_pip.enabled = True
    evpn.advertise_pip.ip = ipaddress.ip_address("192.0.2.5")
    text = render_bgp_instance(instance)
    assert "  advertise-pip ip 192.0.2.5\n" in text
    evpn.advertise_pip.mac = "00:11:22:33:44:55"
    text = render_bgp_instance(instance)
    assert "  advertise-pip ip 192.0.2.5 mac 00:11:22:33:44:55\n" in text


def test_evpn_type5_network_statement():
    instance = _new_instance(vrf="TEN1")
    evpn = instance.afi_safis.l2vpn_evpn
    net = EvpnAf.Network(
        prefix=ipaddress.ip_network("203.0.113.0/24"),
        ethtag=0,
        label=4001,
        esi="00:00:00:00:00:00:00:00:00:00",
        gwip=ipaddress.ip_address("192.0.2.6"),
        routermac="00:11:22:33:44:66",
    )
    net.rd.as2.administrator = 65000
    net.rd.as2.assigned_number = 500
    evpn.network.append(net)
    text = render_bgp_instance(instance)
    assert (
        "  network 203.0.113.0/24 rd 65000:500 ethtag 0 label 4001"
        " esi 00:00:00:00:00:00:00:00:00:00 gwip 192.0.2.6"
        " routermac 00:11:22:33:44:66\n" in text
    )


def test_per_vni_advertise_overrides():
    instance = _new_instance()
    vni = EvpnAf.Vni(vni_id=100)
    vni.advertise_default_gw = True
    vni.advertise_svi_ip = True
    vni.advertise_subnet = True
    instance.afi_safis.l2vpn_evpn.vni.append(vni)
    text = render_bgp_instance(instance)
    assert "   advertise-default-gw\n" in text
    assert "   advertise-svi-ip\n" in text
    assert "   advertise-subnet\n" in text
    assert text.index("  vni 100\n") < text.index("   advertise-default-gw\n")
    assert text.index("   advertise-subnet\n") < text.index("  exit-vni\n")
